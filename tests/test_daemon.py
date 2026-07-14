from fastapi.testclient import TestClient

from backend import daemon


def test_status_sync_play_contract(monkeypatch) -> None:
    kicks: list[int] = []
    monkeypatch.setattr(daemon.catalog_sync, "kick", lambda: kicks.append(1) or True)
    monkeypatch.setattr(daemon.catalog_sync, "is_syncing", lambda: True)
    monkeypatch.setattr(daemon.catalog_sync, "current_track", lambda: None)
    monkeypatch.setattr(
        daemon.db,
        "connect",
        lambda: (_ for _ in ()).throw(RuntimeError("no db in unit test")),
    )
    client = TestClient(daemon.app)

    status = client.get("/status").json()
    assert status["ok"] is True
    assert status["syncing"] is True
    assert status["current"] is None
    assert "tracks" in status
    assert "playlists" in status
    assert "initialized" not in status

    assert client.post("/sync").json() == {"ok": True, "syncing": True}
    assert client.post("/play").json() == {"ok": True, "play": "not_implemented"}
    assert len(kicks) == 2


def test_quit_sets_should_exit(monkeypatch) -> None:
    class FakeServer:
        should_exit = False

    fake = FakeServer()
    monkeypatch.setattr(daemon, "_server", fake)
    client = TestClient(daemon.app)

    assert client.post("/quit").json() == {"ok": True}
    assert fake.should_exit is True
