import math
import random

from backend.music.embeddings import EMBED_DIM
from backend.storage import db
from backend import orchestrator
from backend.music import recommend
from backend.music.playback import FakePlayback


def _unit(seed: float) -> list[float]:
    raw = [math.sin(seed + i * 0.17) for i in range(EMBED_DIM)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


def _fill_catalog(conn, n: int = 50) -> list[int]:
    ids: list[int] = []
    for i in range(n):
        tid = db.upsert_track(
            conn,
            spotify_id=f"sp:{i}",
            name=f"T{i}",
            artists=f"A{i}",
        )
        db.upsert_embedding(conn, tid, _unit(i * 0.37))
        ids.append(tid)
    return ids


def test_fake_playback_records_block() -> None:
    port = FakePlayback()
    tracks = [{"spotify_id": "a", "name": "A", "track_id": 1}]
    port.start_block(tracks)
    assert port.last_block == tracks
    assert port.get_state() is not None
    assert port.get_state().track_id == "a"


def test_play_not_ready(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _fill_catalog(conn, n=10)
    session = orchestrator.Orchestrator(
        playback=FakePlayback(),
        rng=random.Random(0),
    )
    result = session.play(conn)
    assert result["ok"] is False
    assert result["error"] == "not_ready"
    assert result["indexed"] == 10
    assert session.mode == orchestrator.MODE_IDLE


def test_play_starts_block_and_cools_down(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _fill_catalog(conn, n=50)
    fake = FakePlayback()
    session = orchestrator.Orchestrator(playback=fake, rng=random.Random(1), now=1_000.0)
    result = session.play(conn)
    assert result["ok"] is True
    assert result["playing"] is True
    assert result["mode"] == orchestrator.MODE_ATTACHED
    assert len(result["block"]["tracks"]) == recommend.DEFAULT_N
    assert fake.start_count == 1
    assert session.expected_id == result["block"]["tracks"][0]["spotify_id"]
    # only current track cooled at start
    first_id = result["block"]["tracks"][0]["track_id"]
    assert first_id in session.cooldown


def test_play_idempotent_when_attached(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _fill_catalog(conn, n=50)
    fake = FakePlayback()
    session = orchestrator.Orchestrator(playback=fake, rng=random.Random(2))
    first = session.play(conn)
    assert first["ok"]
    second = session.play(conn)
    assert second["ok"] is True
    assert second.get("resumed") is True
    assert fake.start_count == 1


def test_tick_yields_on_foreign_track(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _fill_catalog(conn, n=50)
    fake = FakePlayback()
    session = orchestrator.Orchestrator(playback=fake, rng=random.Random(3))
    assert session.play(conn)["ok"]
    fake.set_state(track_id="totally-foreign", progress_ms=1000)
    out = session.tick(conn)
    assert out["event"] == "yielded"
    assert session.mode == orchestrator.MODE_YIELDED


def test_tick_advances_within_plan(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _fill_catalog(conn, n=50)
    fake = FakePlayback()
    session = orchestrator.Orchestrator(playback=fake, rng=random.Random(4))
    result = session.play(conn)
    tracks = result["block"]["tracks"]
    second = str(tracks[1]["spotify_id"])
    fake.set_state(track_id=second, progress_ms=0, duration_ms=200_000)
    out = session.tick(conn)
    assert out["event"] in {"advanced", "skipped"}
    assert session.expected_id == second
    assert session.mode == orchestrator.MODE_ATTACHED


def test_advance_plays_next(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _fill_catalog(conn, n=50)
    fake = FakePlayback()
    session = orchestrator.Orchestrator(playback=fake, rng=random.Random(5))
    first = session.play(conn)
    assert first["ok"]
    t0 = first["block"]["tracks"][0]["spotify_id"]
    t1 = first["block"]["tracks"][1]["spotify_id"]
    advanced = session.advance(conn)
    assert advanced["ok"] is True
    assert session.expected_id == t1
    assert fake.play_uri_calls[-1] == t1
    assert t0 != t1


def test_advance_without_play_fails(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _fill_catalog(conn, n=50)
    session = orchestrator.Orchestrator(playback=FakePlayback(), rng=random.Random(0))
    result = session.advance(conn)
    assert result["ok"] is False
    assert result["error"] == "not_playing"


def test_play_after_yield_reattaches(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _fill_catalog(conn, n=50)
    fake = FakePlayback()
    session = orchestrator.Orchestrator(playback=fake, rng=random.Random(6))
    session.play(conn)
    fake.set_state(track_id="foreign")
    session.tick(conn)
    assert session.mode == orchestrator.MODE_YIELDED
    again = session.play(conn)
    assert again["ok"] is True
    assert session.mode == orchestrator.MODE_ATTACHED
    assert again.get("resumed") is False


def test_status_snapshot_fields(tmp_path) -> None:
    conn = db.connect(tmp_path / "c.db")
    _fill_catalog(conn, n=50)
    session = orchestrator.Orchestrator(playback=FakePlayback(), rng=random.Random(7))
    snap = session.status_snapshot(conn)
    assert snap["mode"] == orchestrator.MODE_IDLE
    assert snap["recommend_ready"] is True
    session.play(conn)
    snap2 = session.status_snapshot(conn)
    assert snap2["mode"] == orchestrator.MODE_ATTACHED
    assert snap2["virtual_queue"]
    assert snap2["now_playing"] is not None
