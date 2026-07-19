import math
import random

from claude_dj import session as orchestrator
import claude_dj.session.session as session_mod
from claude_dj.embeddings import EMBED_DIM
from claude_dj.playback import FakePlayback
from claude_dj.catalog import db


def _vec(seed: float) -> list[float]:
    raw = [math.sin(seed + i * 0.17) for i in range(EMBED_DIM)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


def _seed_catalog(conn, n: int = 55) -> list[int]:
    ids: list[int] = []
    for i in range(n):
        tid = db.upsert_track(
            conn,
            spotify_id=f"sp:{i}",
            name=f"T{i}",
            artists=f"A{i}",
        )
        db.upsert_embedding(conn, tid, _vec(i * 0.3))
        ids.append(tid)
    return ids


def test_play_mints_and_starts(tmp_path, monkeypatch) -> None:
    conn = db.connect(tmp_path / "c.db")
    _seed_catalog(conn)
    monkeypatch.setattr(
        session_mod.spotify,
        "iter_top_tracks",
        lambda *a, **k: iter([{"spotify_id": "sp:0"}]),
    )
    monkeypatch.setattr(
        session_mod.spotify,
        "iter_recently_played",
        lambda *a, **k: iter([]),
    )
    # Force a tops mode (not recently_played)
    monkeypatch.setattr(
        session_mod.random,
        "choice",
        lambda seq: "short_term" if seq is session_mod._SEED_MODES else seq[0],
    )

    fake = FakePlayback()
    session = orchestrator.Session(playback=fake)
    out = session.play(conn)

    assert out["ok"] is True
    assert out.get("resumed") is not True
    assert fake.start_count == 1
    # Pair-mint: two blocks loaded in one start_block.
    assert len(fake.last_block or []) >= 6
    assert session.mode == orchestrator.MODE_ATTACHED
    assert session.focus is not None
    assert len(session.plan.tracks) >= 6
    assert out.get("size") == len(session.plan.tracks)
    assert out.get("seed_mode") == "short_term"


def test_play_recently_played_seed_mode(tmp_path, monkeypatch) -> None:
    conn = db.connect(tmp_path / "c.db")
    _seed_catalog(conn)
    monkeypatch.setattr(
        session_mod.random,
        "choice",
        lambda seq: "recently_played" if seq is session_mod._SEED_MODES else seq[0],
    )
    monkeypatch.setattr(
        session_mod.spotify,
        "iter_recently_played",
        lambda *a, **k: iter([{"spotify_id": "sp:1"}]),
    )
    monkeypatch.setattr(
        session_mod.spotify,
        "iter_top_tracks",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("should not call tops")),
    )

    fake = FakePlayback()
    session = orchestrator.Session(playback=fake)
    out = session.play(conn)

    assert out["ok"] is True
    assert out.get("seed_mode") == "recently_played"
    assert out.get("source") == "tops"
    assert session.taste is not None


def test_play_empty_catalog_not_ready(tmp_path, monkeypatch) -> None:
    conn = db.connect(tmp_path / "empty.db")
    monkeypatch.setattr(session_mod.spotify, "iter_top_tracks", lambda *a, **k: iter([]))
    monkeypatch.setattr(
        session_mod.spotify, "iter_recently_played", lambda *a, **k: iter([])
    )
    fake = FakePlayback()
    session = orchestrator.Session(playback=fake)
    out = session.play(conn)
    assert out["ok"] is False
    assert out["error"] == "not_ready"
    assert out["indexed"] == 0
    assert fake.start_count == 0
    assert session.mode == orchestrator.MODE_IDLE


def test_play_seed_failure_still_plays(tmp_path, monkeypatch) -> None:
    conn = db.connect(tmp_path / "c.db")
    _seed_catalog(conn)

    def boom(*a, **k):
        raise RuntimeError("spotify down")

    monkeypatch.setattr(session_mod.spotify, "iter_top_tracks", boom)
    monkeypatch.setattr(session_mod.spotify, "iter_recently_played", boom)

    fake = FakePlayback()
    session = orchestrator.Session(playback=fake)
    out = session.play(conn)

    assert out["ok"] is True
    assert fake.start_count == 1
    assert session.mode == orchestrator.MODE_ATTACHED
    assert session.taste is None
    assert out.get("source") == "random"
    assert "seed_error" in out
    assert "spotify down" in out["seed_error"]


def test_play_idempotent_when_attached(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    fake = FakePlayback()
    session = orchestrator.Session(playback=fake)
    tracks = [
        {"spotify_id": "a", "track_id": 1},
        {"spotify_id": "b", "track_id": 2},
    ]
    session.plan.replace(tracks)
    session.mode = orchestrator.MODE_ATTACHED
    fake.start_block(tracks)

    out = session.play(conn)
    assert out["ok"] is True
    assert out.get("resumed") is True
    assert fake.start_count == 1


def test_tick_foreign_track_idles_and_requests_quit() -> None:
    fake = FakePlayback()
    session = orchestrator.Session(playback=fake)
    tracks = [{"spotify_id": "a", "track_id": 1}]
    session.plan.replace(tracks)
    session.mode = orchestrator.MODE_ATTACHED
    session.focus = [1.0]
    session.taste = [1.0]
    session.cooldown = {1: 999.0}
    fake.start_block(tracks)
    fake.set_state(track_id="totally-foreign", progress_ms=1000)

    out = session.tick(None)
    assert out["event"] == "foreign"
    assert out.get("quit") is True
    assert session.mode == orchestrator.MODE_IDLE
    assert session.virtual_queue == []
    assert session.focus is None
    assert session.taste is None
    assert session.cooldown == {}


def test_tick_advances_within_first_block() -> None:
    fake = FakePlayback()
    session = orchestrator.Session(playback=fake)
    # Two blocks of 3: landing on b is still in block 0 → no mint.
    tracks = [
        {"spotify_id": "a", "track_id": 1},
        {"spotify_id": "b", "track_id": 2},
        {"spotify_id": "c", "track_id": 3},
        {"spotify_id": "d", "track_id": 4},
        {"spotify_id": "e", "track_id": 5},
        {"spotify_id": "f", "track_id": 6},
    ]
    session.plan.replace(tracks)
    session._block_ends = [3, 6]
    session.mode = orchestrator.MODE_ATTACHED
    session.focus = [1.0]
    fake.start_block(tracks)
    starts = fake.start_count
    fake.set_state(track_id="b", progress_ms=0, duration_ms=200_000)

    out = session.tick(None)
    assert out["event"] == "advanced"
    assert session.expected_id == "b"
    assert fake.start_count == starts
    assert session.mode == orchestrator.MODE_ATTACHED


def test_tick_pause_does_not_mint(tmp_path, monkeypatch) -> None:
    conn = db.connect(tmp_path / "c.db")
    _seed_catalog(conn)
    monkeypatch.setattr(
        session_mod.spotify,
        "iter_top_tracks",
        lambda *a, **k: iter([]),
    )
    monkeypatch.setattr(
        session_mod.spotify,
        "iter_recently_played",
        lambda *a, **k: iter([]),
    )

    fake = FakePlayback()
    session = orchestrator.Session(playback=fake)
    assert session.play(conn)["ok"] is True
    starts = fake.start_count
    n = len(session.plan.tracks)

    cur = session.plan.current()
    assert cur is not None
    fake.set_state(
        track_id=str(cur["spotify_id"]),
        is_playing=False,
        progress_ms=40_000,
        duration_ms=180_000,
    )

    out = session.tick(conn)
    assert out["ok"] is True
    assert out.get("event") == "paused"
    assert fake.start_count == starts
    assert len(session.plan.tracks) == n


def test_tick_entering_second_block_mints_one_more(tmp_path, monkeypatch) -> None:
    """When playback enters the last loaded block, mint exactly one new block."""
    conn = db.connect(tmp_path / "c.db")
    _seed_catalog(conn, n=80)
    monkeypatch.setattr(
        session_mod.spotify,
        "iter_top_tracks",
        lambda *a, **k: iter([]),
    )
    monkeypatch.setattr(
        session_mod.spotify,
        "iter_recently_played",
        lambda *a, **k: iter([]),
    )

    fake = FakePlayback()
    session = orchestrator.Session(playback=fake)
    assert session.play(conn)["ok"] is True
    assert len(session._block_ends) == 2
    n_before = len(session.plan.tracks)
    # First track of the second block.
    second_start = session._block_ends[0]
    head_of_second = session.plan.tracks[second_start]
    starts = fake.start_count
    fake.set_state(
        track_id=str(head_of_second["spotify_id"]),
        progress_ms=0,
        duration_ms=180_000,
    )

    out = session.tick(conn)
    assert out["ok"] is True
    assert out.get("event") == "minted"
    assert fake.start_count > starts
    assert len(session._block_ends) == 3
    assert len(session.plan.tracks) > n_before
    assert session.expected_id == str(head_of_second["spotify_id"])
    assert session.mode == orchestrator.MODE_ATTACHED


def test_tick_same_in_first_block_does_not_mint(tmp_path, monkeypatch) -> None:
    conn = db.connect(tmp_path / "c.db")
    _seed_catalog(conn)
    monkeypatch.setattr(
        session_mod.spotify,
        "iter_top_tracks",
        lambda *a, **k: iter([]),
    )
    monkeypatch.setattr(
        session_mod.spotify,
        "iter_recently_played",
        lambda *a, **k: iter([]),
    )

    fake = FakePlayback()
    session = orchestrator.Session(playback=fake)
    assert session.play(conn)["ok"] is True
    starts = fake.start_count
    n = len(session.plan.tracks)
    cur = session.plan.current()
    assert cur is not None
    fake.set_state(
        track_id=str(cur["spotify_id"]),
        progress_ms=10_000,
        duration_ms=180_000,
    )

    out = session.tick(conn)
    assert out["ok"] is True
    assert out.get("event") == "ok"
    assert fake.start_count == starts
    assert len(session.plan.tracks) == n
    assert len(session._block_ends) == 2


def test_status_fields(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    session = orchestrator.Session(playback=FakePlayback())
    snap = session.status(conn)
    assert snap["indexed"] == 0
    assert snap["now_playing"] is None


def test_status_idle_reports_spotify_playback(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    fake = FakePlayback()
    fake.set_state(
        track_id="sp:x",
        is_playing=True,
        progress_ms=12_000,
        duration_ms=180_000,
        name="Baby",
        artists="Four Tet",
    )
    session = orchestrator.Session(playback=fake)
    snap = session.status(conn)
    assert snap["mode"] == "idle"
    assert snap["now_playing"] == {
        "name": "Baby",
        "artists": "Four Tet",
        "progress_ms": 12_000,
        "duration_ms": 180_000,
        "spotify_id": "sp:x",
    }


def test_quit_jam_resets_session() -> None:
    fake = FakePlayback()
    session = orchestrator.Session(playback=fake)
    session.mode = "attached"
    out = session.quit_jam()
    assert out == {"ok": True, "mode": "idle", "was": "attached"}
    assert session.mode == "idle"
