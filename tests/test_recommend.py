import math
import random

from backend.music.embeddings import EMBED_DIM
from backend.storage import db
from backend.music import recommend


def _unit(seed: float) -> list[float]:
    raw = [math.sin(seed + i * 0.17) for i in range(EMBED_DIM)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


def _axis(i: int, value: float = 1.0) -> list[float]:
    v = [0.0] * EMBED_DIM
    v[i % EMBED_DIM] = value
    return v


def _fill_catalog(conn, n: int = 50, seed_base: float = 0.0) -> list[int]:
    ids: list[int] = []
    for i in range(n):
        tid = db.upsert_track(
            conn,
            spotify_id=f"sp:{i}",
            name=f"T{i}",
            artists=f"A{i}",
        )
        db.upsert_embedding(conn, tid, _unit(seed_base + i * 0.37))
        ids.append(tid)
    return ids


def test_next_block_seed_blend_and_normalize() -> None:
    last = [1.0] + [0.0] * (EMBED_DIM - 1)
    recency = [0.0, 1.0] + [0.0] * (EMBED_DIM - 2)
    out = recommend.next_block_seed(last, recency)
    assert abs(math.sqrt(sum(x * x for x in out)) - 1.0) < 1e-6
    # 0.7 last + 0.3 recency → first axis larger than second before/after L2
    assert out[0] > out[1] > 0


def test_next_block_seed_without_recency_is_last() -> None:
    last = _unit(1.0)
    out = recommend.next_block_seed(last, None)
    assert out == list(last)


def test_next_block_seed_degenerate_fallback() -> None:
    z = [0.0] * EMBED_DIM
    last = _unit(1.0)
    out = recommend.next_block_seed(last, z)
    assert all(abs(a - b) < 1e-6 for a, b in zip(out, last, strict=True))


def test_sample_seed_from_top_empty(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _fill_catalog(conn, n=50)
    assert (
        recommend.sample_seed_from_top(conn, [], rng=random.Random(0)) is None
    )


def test_sample_seed_from_top_skips_missing(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    ids = _fill_catalog(conn, n=50)
    # only sp:3 is in catalog among tops
    tops = [{"spotify_id": "missing"}, {"spotify_id": "sp:3"}, {"spotify_id": "also-missing"}]
    emb = recommend.sample_seed_from_top(conn, tops, rng=random.Random(0))
    assert emb is not None
    expected = db.get_embedding(conn, ids[3])
    assert expected is not None
    assert all(abs(a - b) < 1e-5 for a, b in zip(emb, expected, strict=True))


def test_sample_seed_from_top_prefers_higher_rank(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    ids = _fill_catalog(conn, n=50)
    tops = [{"spotify_id": f"sp:{i}"} for i in range(10)]
    counts: dict[int, int] = {i: 0 for i in range(10)}
    rng = random.Random(0)
    for _ in range(300):
        emb = recommend.sample_seed_from_top(conn, tops, tau=0.15, rng=rng)
        assert emb is not None
        # match embedding to track
        for i in range(10):
            e = db.get_embedding(conn, ids[i])
            if e and all(abs(a - b) < 1e-5 for a, b in zip(emb, e, strict=True)):
                counts[i] += 1
                break
    assert counts[0] > counts[9]


def test_apply_cooldown() -> None:
    cool: dict[int, float] = {}
    recommend.apply_cooldown(cool, [1, 2], now=100.0)
    assert cool == {1: 100.0, 2: 100.0}


def test_softmax_sample_prefers_nearer() -> None:
    rng = random.Random(0)
    candidates = [
        {"id": 1, "distance": 0.01},
        {"id": 2, "distance": 2.0},
        {"id": 3, "distance": 2.0},
    ]
    counts = {1: 0, 2: 0, 3: 0}
    for _ in range(200):
        pick = recommend.softmax_sample(candidates, tau=0.15, rng=rng)
        counts[int(pick["id"])] += 1
    assert counts[1] > counts[2] + counts[3]


def test_recommend_not_ready(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _fill_catalog(conn, n=10)
    result = recommend.recommend_block(conn, n=3, rng=random.Random(0))
    assert result["ok"] is False
    assert result["error"] == "not_ready"
    assert result["indexed"] == 10


def test_recommend_invalid_n(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _fill_catalog(conn, n=50)
    for n in (2, 6):
        result = recommend.recommend_block(conn, n=n, rng=random.Random(0))
        assert result["ok"] is False
        assert result["error"] == "invalid_n"


def test_recommend_full_block_unique(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _fill_catalog(conn, n=50)
    result = recommend.recommend_block(conn, n=5, rng=random.Random(1))
    assert result["ok"] is True
    assert result["n"] == 5
    assert len(result["tracks"]) == 5
    ids = [t["track_id"] for t in result["tracks"]]
    assert len(set(ids)) == 5
    assert result["session_start_embed"] is not None
    assert result["last_embed"] is not None
    for t in result["tracks"]:
        assert "spotify_id" in t
        assert "name" in t
        assert "artists" in t
        assert "distance" in t


def test_recommend_cooldown_excludes(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    # Cluster: many near origin axis-0, one far on axis-1
    ids = []
    for i in range(50):
        tid = db.upsert_track(conn, spotify_id=f"sp:{i}", name=f"T{i}", artists="A")
        if i < 49:
            v = _axis(0, 1.0)
            # slight perturbation so they are not identical for uniqueness of rows
            v = list(v)
            v[2] = 0.01 * i
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            v = [x / norm for x in v]
        else:
            v = _axis(1, 1.0)
        db.upsert_embedding(conn, tid, v)
        ids.append(tid)

    seed = db.get_embedding(conn, ids[0])
    assert seed is not None
    # Ban almost everything near the seed
    now = 1_000_000.0
    cooldown = {tid: now for tid in ids[:48]}
    result = recommend.recommend_block(
        conn,
        n=3,
        seed_embed=seed,
        session_start_embed=seed,
        cooldown=cooldown,
        now=now,
        rng=random.Random(0),
        neighbor_k=50,
    )
    assert result["ok"] is False
    assert result["error"] == "insufficient_eligible"


def test_recommend_cooldown_expires(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    ids = _fill_catalog(conn, n=50)
    seed = db.get_embedding(conn, ids[0])
    assert seed is not None
    now = 10_000.0
    cooldown = {ids[1]: now - (3 * 3600 + 1)}
    result = recommend.recommend_block(
        conn,
        n=3,
        seed_embed=seed,
        session_start_embed=seed,
        cooldown=cooldown,
        now=now,
        rng=random.Random(2),
    )
    assert result["ok"] is True
    # expired cooldown must not hard-fail
    assert len(result["tracks"]) == 3


def test_recommend_cold_start_deterministic_with_rng(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    ids = _fill_catalog(conn, n=50)
    r1 = recommend.recommend_block(conn, n=3, rng=random.Random(42))
    r2 = recommend.recommend_block(conn, n=3, rng=random.Random(42))
    assert r1["ok"] and r2["ok"]
    assert [t["track_id"] for t in r1["tracks"]] == [t["track_id"] for t in r2["tracks"]]
    # session start should match an indexed embedding
    start = r1["session_start_embed"]
    assert any(
        all(abs(a - b) < 1e-5 for a, b in zip(start, db.get_embedding(conn, tid), strict=True))
        for tid in ids
        if db.get_embedding(conn, tid) is not None
    )


def test_next_block_seed_used_by_caller(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _fill_catalog(conn, n=50)
    first = recommend.recommend_block(conn, n=3, rng=random.Random(7))
    assert first["ok"]
    recency = first["session_start_embed"]
    seed = recommend.next_block_seed(first["last_embed"], recency)
    second = recommend.recommend_block(
        conn,
        n=3,
        seed_embed=seed,
        session_start_embed=first["session_start_embed"],
        rng=random.Random(8),
    )
    assert second["ok"]
