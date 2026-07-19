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

    assert client.post("/sync").json() == {"ok": True, "syncing": True}
    jam_body = client.post("/jam").json()
    assert jam_body["ok"] is False
    assert len(kicks) == 2


def test_play_empty_catalog_returns_not_ready(monkeypatch, tmp_path) -> None:
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
    monkeypatch.setattr(daemon_mod, "_session", Session(playback=fake))
    client = TestClient(daemon_mod.app)

    body = client.post("/jam").json()
    assert body["ok"] is False
    assert body["error"] == "not_ready"
    assert body["indexed"] == 0
    assert body["syncing"] is True
    assert "hint" in body
    assert fake.start_count == 0


def test_devices_list_and_select(monkeypatch) -> None:
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
    client = TestClient(daemon_mod.app)

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
