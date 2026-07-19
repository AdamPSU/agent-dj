"""Focus + Taste recommender unit tests."""

from __future__ import annotations

import math
import random

from claude_dj import recommend
from claude_dj.embeddings import EMBED_DIM
from claude_dj.catalog import db


def _vec(seed: float) -> list[float]:
    raw = [math.sin(seed + i * 0.17) for i in range(EMBED_DIM)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


def _axis(i: int) -> list[float]:
    v = [0.0] * EMBED_DIM
    v[i % EMBED_DIM] = 1.0
    return v


def _seed_catalog(conn, n: int = 55, *, base: float = 0.0) -> list[int]:
    ids: list[int] = []
    for i in range(n):
        tid = db.upsert_track(
            conn,
            spotify_id=f"sp:{i}",
            name=f"T{i}",
            artists=f"A{i}",
        )
        db.upsert_embedding(conn, tid, _vec(base + i * 0.3))
        ids.append(tid)
    pid = db.upsert_playlist(conn, spotify_id="pl:test", name="Test")
    db.set_playlist_tracks(conn, pid, [(tid, i, None) for i, tid in enumerate(ids)])
    return ids


def _seed_two_playlists(conn):
    """P1 near _vec(0..); P2 near _vec(100..)."""
    p1 = db.upsert_playlist(conn, spotify_id="pl:1", name="P1")
    p2 = db.upsert_playlist(conn, spotify_id="pl:2", name="P2")
    m1: list[tuple[int, int, None]] = []
    m2: list[tuple[int, int, None]] = []
    ids1: list[int] = []
    ids2: list[int] = []
    for i in range(10):
        tid = db.upsert_track(conn, spotify_id=f"sp:{i}", name=f"T{i}", artists="A")
        db.upsert_embedding(conn, tid, _vec(i * 0.3))
        m1.append((tid, i, None))
        ids1.append(tid)
    for i in range(10, 20):
        tid = db.upsert_track(conn, spotify_id=f"sp:{i}", name=f"T{i}", artists="A")
        db.upsert_embedding(conn, tid, _vec(100.0 + (i - 10) * 0.3))
        m2.append((tid, i - 10, None))
        ids2.append(tid)
    db.set_playlist_tracks(conn, p1, m1)
    db.set_playlist_tracks(conn, p2, m2)
    return p1, p2, ids1, ids2


def test_l2_normalize_unit_length() -> None:
    out = recommend.l2_normalize([3.0, 4.0] + [0.0] * (EMBED_DIM - 2))
    assert abs(math.sqrt(sum(x * x for x in out)) - 1.0) < 1e-6


def test_softmax_sample_prefers_high_score() -> None:
    items = ["a", "b", "c"]
    scores = [0.0, 10.0, 0.0]
    rng = random.Random(0)
    picks = [
        recommend.softmax_sample(items, scores, tau=0.15, rng=rng) for _ in range(40)
    ]
    assert picks.count("b") >= 30


def test_block_returns_full_size_unique(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _seed_catalog(conn, n=55)
    result = recommend.recommend_block(
        conn,
        focus=_vec(0.0),
        size=5,
        rng=random.Random(0),
    )
    assert len(result.tracks) == 5
    assert result.size == 5
    ids = [t["track_id"] for t in result.tracks]
    assert len(set(ids)) == 5
    for t in result.tracks:
        assert "spotify_id" in t
        assert "track_id" in t


def test_respects_cooldown(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    ids = _seed_catalog(conn, n=55)
    cooled = ids[0]
    cooldown = {cooled: 9_999_999_999.0}
    result = recommend.recommend_block(
        conn,
        focus=db.get_embedding(conn, cooled),
        size=5,
        cooldown=cooldown,
        now=1_000.0,
        rng=random.Random(1),
    )
    assert cooled not in {t["track_id"] for t in result.tracks}


def test_empty_neighborhood_ends_block_early(tmp_path) -> None:
    """When nothing is eligible, return what we have (possibly empty)."""
    conn = db.connect(tmp_path / "c.db")
    ids = _seed_catalog(conn, n=55)
    now = 1_000.0
    cooldown = {tid: now + 10_000 for tid in ids}
    result = recommend.recommend_block(
        conn,
        focus=_vec(0.0),
        size=5,
        cooldown=cooldown,
        now=now,
        rng=random.Random(0),
    )
    assert result.tracks == []
    assert result.size == 0


def test_focus_moves_after_block(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _seed_catalog(conn, n=55)
    focus_in = _vec(0.0)
    result = recommend.recommend_block(
        conn,
        focus=focus_in,
        size=5,
        rng=random.Random(0),
    )
    assert result.focus != focus_in
    assert abs(math.sqrt(sum(x * x for x in result.focus)) - 1.0) < 1e-5


def test_taste_biases_toward_taste_cluster(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    # One playlist so lock doesn't isolate clusters from each other.
    pid = db.upsert_playlist(conn, spotify_id="pl:mix", name="Mix")
    members: list[tuple[int, int, None]] = []
    b_ids = []
    n = 0
    for i in range(30):
        tid = db.upsert_track(conn, spotify_id=f"a:{i}", name=f"A{i}", artists="A")
        v = _axis(0)
        v[2] = 0.01 * i
        db.upsert_embedding(conn, tid, recommend.l2_normalize(v))
        members.append((tid, n, None))
        n += 1
    for i in range(30):
        tid = db.upsert_track(conn, spotify_id=f"b:{i}", name=f"B{i}", artists="B")
        v = _axis(1)
        v[3] = 0.01 * i
        db.upsert_embedding(conn, tid, recommend.l2_normalize(v))
        b_ids.append(tid)
        members.append((tid, n, None))
        n += 1
    db.set_playlist_tracks(conn, pid, members)

    focus = recommend.l2_normalize(_axis(0))
    taste = recommend.l2_normalize(_axis(1))
    b_set = set(b_ids)

    with_t = recommend.recommend_block(
        conn, focus=focus, taste=taste, size=5, rng=random.Random(0)
    )
    without = recommend.recommend_block(
        conn, focus=focus, taste=None, size=5, rng=random.Random(0)
    )
    b_with = sum(1 for t in with_t.tracks if t["track_id"] in b_set)
    b_without = sum(1 for t in without.tracks if t["track_id"] in b_set)
    assert b_with >= b_without


def test_block_single_playlist(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    p1, p2, ids1, ids2 = _seed_two_playlists(conn)
    block = recommend.recommend_block(
        conn, focus=_vec(0.0), size=5, rng=random.Random(0)
    )
    assert block.size == 5
    assert block.playlist_id in {p1, p2}
    allowed = set(ids1 if block.playlist_id == p1 else ids2)
    assert {t["track_id"] for t in block.tracks} <= allowed
    assert all(t.get("playlist_id") == block.playlist_id for t in block.tracks)


def test_short_playlist_block(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    p = db.upsert_playlist(conn, spotify_id="pl:s", name="Small")
    ids = []
    for i in range(2):
        tid = db.upsert_track(conn, spotify_id=f"s{i}", name=f"S{i}", artists="A")
        db.upsert_embedding(conn, tid, _vec(float(i)))
        ids.append(tid)
    db.set_playlist_tracks(conn, p, [(t, i, None) for i, t in enumerate(ids)])
    block = recommend.recommend_block(
        conn, focus=_vec(0.0), size=5, rng=random.Random(0)
    )
    assert block.playlist_id == p
    assert 1 <= block.size <= 2
    assert {t["track_id"] for t in block.tracks} <= set(ids)


def test_soft_switch_prefers_other_playlist(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    p1, p2, _ids1, _ids2 = _seed_two_playlists(conn)
    block = recommend.recommend_block(
        conn,
        focus=_vec(100.0),
        size=5,
        previous_playlist_id=p1,
        rng=random.Random(0),
    )
    assert block.playlist_id == p2


def test_multi_membership_does_not_split_block(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    p1 = db.upsert_playlist(conn, spotify_id="pl:1", name="P1")
    p2 = db.upsert_playlist(conn, spotify_id="pl:2", name="P2")
    shared = []
    for i in range(6):
        tid = db.upsert_track(conn, spotify_id=f"sh{i}", name=f"S{i}", artists="A")
        db.upsert_embedding(conn, tid, _vec(i * 0.2))
        shared.append(tid)
    only2 = db.upsert_track(conn, spotify_id="only2", name="O", artists="A")
    db.upsert_embedding(conn, only2, _vec(50.0))
    db.set_playlist_tracks(conn, p1, [(t, i, None) for i, t in enumerate(shared)])
    db.set_playlist_tracks(
        conn, p2, [(t, i, None) for i, t in enumerate(shared + [only2])]
    )
    block = recommend.recommend_block(
        conn, focus=_vec(0.0), size=5, rng=random.Random(1)
    )
    assert block.playlist_id is not None
    for t in block.tracks:
        pls = {int(r["id"]) for r in db.list_playlists_for_track(conn, t["track_id"])}
        assert block.playlist_id in pls


def test_advance_focus_without_taste_stays_near() -> None:
    f = _vec(1.0)
    out = recommend.advance_focus(f, None, rng=random.Random(0), noise=0.01)
    dot = sum(a * b for a, b in zip(recommend.l2_normalize(f), out))
    assert dot > 0.99


def test_advance_focus_with_taste_moves_toward_t() -> None:
    f = _axis(0)
    t = _axis(1)
    out = recommend.advance_focus(f, t, rng=random.Random(0), delta=0.5, noise=0.0)

    def dist(a, b):
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    assert dist(out, recommend.l2_normalize(t)) < dist(
        recommend.l2_normalize(f), recommend.l2_normalize(t)
    )


def test_apply_cooldown_sets_expiry() -> None:
    cd: dict[int, float] = {}
    recommend.apply_cooldown(cd, [1, 2], now=1000.0, seconds=3600)
    assert cd[1] == 4600.0
    assert cd[2] == 4600.0


def test_sample_seed_from_tops_softmax_not_always_first(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    for i in range(10):
        tid = db.upsert_track(conn, spotify_id=f"top:{i}", name=f"T{i}", artists="A")
        db.upsert_embedding(conn, tid, _vec(i))
    top_rows = [{"spotify_id": f"top:{i}"} for i in range(10)]
    picks: set[str] = set()
    for seed in range(30):
        emb = recommend.sample_seed_from_tops(
            conn, top_rows, tau=0.5, rng=random.Random(seed)
        )
        assert emb is not None
        hits = db.similar_tracks(conn, emb, limit=1)
        picks.add(hits[0]["spotify_id"])
    assert len(picks) >= 3


def test_sample_seed_from_tops_empty_intersection(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _seed_catalog(conn, n=5)
    emb = recommend.sample_seed_from_tops(
        conn, [{"spotify_id": "missing"}], rng=random.Random(0)
    )
    assert emb is None


def test_resolve_session_start_with_tops(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _seed_catalog(conn, n=55)
    tid = db.upsert_track(conn, spotify_id="hit", name="Hit", artists="H")
    db.upsert_embedding(conn, tid, _axis(0))
    start = recommend.resolve_session_start(
        conn,
        top_rows=[{"spotify_id": "hit"}, {"spotify_id": "nope"}],
        rng=random.Random(0),
    )
    assert start is not None
    assert start.taste is not None
    assert start.focus is not None
    assert start.source == "tops"


def test_resolve_session_start_fallback_random(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _seed_catalog(conn, n=55)
    start = recommend.resolve_session_start(
        conn,
        top_rows=[{"spotify_id": "not-in-catalog"}],
        rng=random.Random(0),
    )
    assert start is not None
    assert start.taste is None
    assert start.focus is not None
    assert start.source == "random"


def test_resolve_session_start_empty_catalog_returns_none(tmp_path) -> None:
    conn = db.connect(tmp_path / "empty.db")
    start = recommend.resolve_session_start(conn, top_rows=None, rng=random.Random(0))
    assert start is None
