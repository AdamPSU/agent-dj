import json
from unittest.mock import patch

from backend import cli


def test_status_prints_json(capsys) -> None:
    payload = {"ok": True, "pid": 123}
    with patch.object(cli, "request", return_value=payload):
        cli.main(["status"])
    assert json.loads(capsys.readouterr().out) == payload


def test_play_ensures_login_and_daemon_then_posts(capsys) -> None:
    payload = {"ok": True, "playing": True, "block": {"n": 5, "tracks": []}}
    with (
        patch.object(cli, "ensure_spotify_login") as login,
        patch.object(cli, "ensure_daemon") as ensure,
        patch.object(cli, "request", return_value=payload) as request,
    ):
        cli.main(["play"])
    login.assert_called_once_with()
    ensure.assert_called_once_with()
    request.assert_called_once_with("POST", "/play")
    assert json.loads(capsys.readouterr().out) == payload


def test_sync_and_quit_do_not_spawn(capsys) -> None:
    with (
        patch.object(cli, "ensure_daemon") as ensure,
        patch.object(cli, "ensure_spotify_login") as login,
        patch.object(
            cli,
            "request",
            side_effect=[
                {"ok": True, "stub": True},
                {"ok": True},
            ],
        ) as request,
    ):
        cli.main(["sync"])
        cli.main(["quit"])
    ensure.assert_not_called()
    login.assert_not_called()
    assert request.call_args_list[0].args == ("POST", "/sync")
    assert request.call_args_list[1].args == ("POST", "/quit")


def test_device_list_ensures_login_and_daemon(capsys) -> None:
    payload = {"ok": True, "devices": [], "preferred_device_id": None}
    with (
        patch.object(cli, "ensure_spotify_login") as login,
        patch.object(cli, "ensure_daemon") as ensure,
        patch.object(cli, "request", return_value=payload) as request,
    ):
        cli.main(["device"])
    login.assert_called_once_with()
    ensure.assert_called_once_with()
    request.assert_called_once_with("GET", "/devices")
    assert json.loads(capsys.readouterr().out) == payload


def test_device_select_posts_id(capsys) -> None:
    payload = {"ok": True, "preferred_device_id": "dev1"}
    with (
        patch.object(cli, "ensure_spotify_login"),
        patch.object(cli, "ensure_daemon"),
        patch.object(cli, "request", return_value=payload) as request,
    ):
        cli.main(["device", "dev1"])
    request.assert_called_once_with("POST", "/devices/dev1")
    assert json.loads(capsys.readouterr().out) == payload


def test_ensure_spotify_login_uses_ensure_session() -> None:
    with patch("backend.adapters.spotify.ensure_session") as ensure_session:
        cli.ensure_spotify_login()
    ensure_session.assert_called_once_with()


def test_ensure_daemon_noop_when_reachable() -> None:
    with (
        patch.object(cli, "reachable", return_value=True),
        patch.object(cli.subprocess, "Popen") as popen,
    ):
        cli.ensure_daemon()
    popen.assert_not_called()


def test_ensure_daemon_reports_exit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "APP_DIR", tmp_path)
    monkeypatch.setattr(cli, "DAEMON_LOG", tmp_path / "daemon.log")
    monkeypatch.setattr(cli, "DAEMON_WAIT_ATTEMPTS", 3)

    class Dead:
        def poll(self):
            return 1

        @property
        def returncode(self):
            return 1

    (tmp_path / "daemon.log").write_bytes(b"bind failed: address already in use\n")

    with (
        patch.object(cli, "reachable", return_value=False),
        patch.object(cli.subprocess, "Popen", return_value=Dead()),
    ):
        try:
            cli.ensure_daemon()
            assert False, "expected SystemExit"
        except SystemExit as exc:
            msg = str(exc)
            assert "daemon exited" in msg
            assert "address already in use" in msg
