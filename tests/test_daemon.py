import claude_dj.daemon.server as daemon_mod
from fastapi.testclient import TestClient

from claude_dj.playback import FakePlayback
from claude_dj.session import Session


def test_status_sync_jam_contract(monkeypatch) -> None:
    kicks: list[int] = []
    monkeypatch.setattr(daemon_mod.catalog_sync, "kick", lambda: kicks.append(1) or True)
    monkeypatch.setattr(daemon_mod.catalog_sync, "is_syncing", lambda: True)
    monkeypatch.setattr(daemon_mod.catalog_sync, "current_track", lambda: None)
    fake = FakePlayback()
    session = Session(playback=fake)
    monkeypatch.setattr(daemon_mod, "_session", session)
    monkeypatch.setattr(daemon_mod, "_ensure_monitor", lambda: None)

    def bad_connect():
        raise RuntimeError("no db in unit test")

    monkeypatch.setattr(daemon_mod.db, "connect", bad_connect)
    client = TestClient(daemon_mod.app)

    status = client.get("/status").json()
    assert status["ok"] is True
    assert status["syncing"] is True

    sync_body = client.post("/sync").json()
    assert sync_body["ok"] is True
    assert sync_body["syncing"] is True
    jam_body = client.post("/jam").json()
    # No db → play path fails hard from connect, or waiting if session handles it.
    assert jam_body.get("ok") is False or jam_body.get("waiting") is True
    assert len(kicks) == 2


def test_play_empty_catalog_returns_waiting(monkeypatch, tmp_path) -> None:
    from claude_dj.catalog import db

    path = tmp_path / "catalog.db"
    conn = db.connect(path)
    conn.close()

    monkeypatch.setattr(daemon_mod.catalog_sync, "kick", lambda: True)
    monkeypatch.setattr(daemon_mod.catalog_sync, "is_syncing", lambda: True)
    monkeypatch.setattr(daemon_mod, "_ensure_monitor", lambda: None)
    real_connect = db.connect
    monkeypatch.setattr(daemon_mod.db, "connect", lambda: real_connect(path))
    monkeypatch.setattr(
        "claude_dj.session.session.spotify.iter_top_tracks",
        lambda *a, **k: iter([]),
    )
    monkeypatch.setattr(
        "claude_dj.session.session.spotify.iter_recently_played",
        lambda *a, **k: iter([]),
    )

    fake = FakePlayback()
    session = Session(playback=fake)
    monkeypatch.setattr(daemon_mod, "_session", session)
    client = TestClient(daemon_mod.app)

    body = client.post("/jam").json()
    assert body["ok"] is True
    assert body.get("waiting") is True
    assert body["indexed"] == 0
    assert session.auto_jam is True
    assert fake.start_count == 0


def test_devices_list(monkeypatch) -> None:
    from claude_dj.adapters import spotify as spotify_mod

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
    monkeypatch.setattr(spotify_mod, "load_preferred_device_id", lambda: "dev1")
    client = TestClient(daemon_mod.app)

    listed = client.get("/devices").json()
    assert listed["ok"] is True
    assert listed["devices"] == devices
    assert listed["preferred_device_id"] == "dev1"


def test_kill_sets_should_exit(monkeypatch) -> None:
    class FakeServer:
        should_exit = False

    fake_server = FakeServer()
    session = Session(playback=FakePlayback())
    session.mode = "attached"
    monkeypatch.setattr(daemon_mod, "_server", fake_server)
    monkeypatch.setattr(daemon_mod, "_session", session)
    client = TestClient(daemon_mod.app)

    assert client.post("/kill").json() == {"ok": True}
    assert fake_server.should_exit is True
    assert session.mode == "idle"
