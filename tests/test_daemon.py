from fastapi.testclient import TestClient

from backend import daemon


def test_status_start_sync_contract(monkeypatch) -> None:
    monkeypatch.setattr(daemon, "started", False)
    client = TestClient(daemon.app)

    status = client.get("/status").json()
    assert status == {"ok": True, "started": False, "pid": status["pid"]}

    started = client.post("/start").json()
    assert started["ok"] is True
    assert started["started"] is True
    assert started["pid"] == status["pid"]

    again = client.post("/start").json()
    assert again["started"] is True

    assert client.post("/sync").json() == {"ok": True, "stub": True}


def test_quit_sets_should_exit(monkeypatch) -> None:
    class FakeServer:
        should_exit = False

    fake = FakeServer()
    monkeypatch.setattr(daemon, "_server", fake)
    client = TestClient(daemon.app)

    assert client.post("/quit").json() == {"ok": True}
    assert fake.should_exit is True
