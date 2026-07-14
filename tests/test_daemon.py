from fastapi.testclient import TestClient

from backend import daemon
from backend.orchestrator import Orchestrator
from backend.music.playback import FakePlayback


def test_status_sync_play_contract(monkeypatch) -> None:
    kicks: list[int] = []
    monkeypatch.setattr(daemon.catalog_sync, "kick", lambda: kicks.append(1) or True)
    monkeypatch.setattr(daemon.catalog_sync, "is_syncing", lambda: True)
    monkeypatch.setattr(daemon.catalog_sync, "current_track", lambda: None)
    fake = FakePlayback()
    orch = Orchestrator(playback=fake)
    monkeypatch.setattr(daemon, "_orchestrator", orch)
    monkeypatch.setattr(daemon, "_ensure_monitor", lambda: None)

    class Boom:
        def close(self):
            pass

    def bad_connect():
        raise RuntimeError("no db in unit test")

    monkeypatch.setattr(daemon.db, "connect", bad_connect)
    client = TestClient(daemon.app)

    status = client.get("/status").json()
    assert status["ok"] is True
    assert status["syncing"] is True

    assert client.post("/sync").json() == {"ok": True, "syncing": True}
    play_body = client.post("/play").json()
    assert play_body["ok"] is False
    assert len(kicks) == 2


def test_play_uses_orchestrator(monkeypatch, tmp_path) -> None:
    from backend.storage import db
    from backend.music.embeddings import EMBED_DIM
    import math

    def unit(seed: float) -> list[float]:
        raw = [math.sin(seed + i * 0.17) for i in range(EMBED_DIM)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]

    path = tmp_path / "catalog.db"
    conn = db.connect(path)
    for i in range(50):
        tid = db.upsert_track(conn, spotify_id=f"sp:{i}", name=f"T{i}", artists="A")
        db.upsert_embedding(conn, tid, unit(i * 0.3))
    conn.close()

    monkeypatch.setattr(daemon.catalog_sync, "kick", lambda: True)
    monkeypatch.setattr(daemon, "_ensure_monitor", lambda: None)
    real_connect = db.connect
    monkeypatch.setattr(daemon.db, "connect", lambda: real_connect(path))

    fake = FakePlayback()
    monkeypatch.setattr(daemon, "_orchestrator", Orchestrator(playback=fake))
    client = TestClient(daemon.app)

    body = client.post("/play").json()
    assert body["ok"] is True
    assert body["playing"] is True
    assert body["mode"] == "attached"
    assert len(body["block"]["tracks"]) == 5
    assert fake.start_count == 1

    again = client.post("/play").json()
    assert again["ok"] is True
    assert again.get("resumed") is True
    assert fake.start_count == 1

    status = client.get("/status").json()
    assert status["mode"] == "attached"
    assert status["recommend_ready"] is True
    assert status["indexed"] == 50


def test_devices_list_and_select(monkeypatch) -> None:
    from backend.adapters import spotify as spotify_mod

    devices = [
        {
            "id": "dev1",
            "name": "Mac",
            "type": "Computer",
            "is_active": True,
            "is_restricted": False,
            "volume_percent": 50,
        }
    ]
    monkeypatch.setattr(spotify_mod, "list_devices", lambda: devices)
    monkeypatch.setattr(spotify_mod, "load_preferred_device_id", lambda: None)
    saved: list[str] = []
    monkeypatch.setattr(
        spotify_mod, "save_preferred_device_id", lambda did: saved.append(did)
    )
    transferred: list[str] = []
    monkeypatch.setattr(
        spotify_mod,
        "transfer_playback",
        lambda did, play=False: transferred.append(did),
    )
    client = TestClient(daemon.app)

    listed = client.get("/devices").json()
    assert listed["ok"] is True
    assert listed["devices"] == devices

    selected = client.post("/devices/dev1").json()
    assert selected["ok"] is True
    assert selected["preferred_device_id"] == "dev1"
    assert saved == ["dev1"]
    assert transferred == ["dev1"]

    bad = client.post("/devices/nope").json()
    assert bad["ok"] is False
    assert bad["error"] == "unknown_device"


def test_quit_sets_should_exit(monkeypatch) -> None:
    class FakeServer:
        should_exit = False

    fake = FakeServer()
    monkeypatch.setattr(daemon, "_server", fake)
    client = TestClient(daemon.app)

    assert client.post("/quit").json() == {"ok": True}
    assert fake.should_exit is True
