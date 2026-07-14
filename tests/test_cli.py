import json
from unittest.mock import patch

from backend import cli


def test_status_prints_json(capsys) -> None:
    payload = {"ok": True, "started": True, "pid": 123}
    with patch.object(cli, "request", return_value=payload):
        cli.main(["status"])
    assert json.loads(capsys.readouterr().out) == payload


def test_start_ensures_login_and_daemon_then_posts(capsys) -> None:
    payload = {"ok": True, "started": True, "pid": 9}
    with (
        patch.object(cli, "ensure_spotify_login") as login,
        patch.object(cli, "ensure_daemon") as ensure,
        patch.object(cli, "request", return_value=payload) as request,
    ):
        cli.main(["start"])
    login.assert_called_once_with()
    ensure.assert_called_once_with()
    request.assert_called_once_with("POST", "/start")
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


def test_spotify_login_command(capsys) -> None:
    with patch("backend.adapters.spotify.login", return_value={"ok": True, "path": "/t"}):
        cli.main(["spotify-login"])
    assert json.loads(capsys.readouterr().out) == {"ok": True, "path": "/t"}


def test_ensure_spotify_login_skips_when_file_exists(tmp_path, monkeypatch) -> None:
    path = tmp_path / "spotify_tokens.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "SPOTIFY_TOKEN_PATH", path)
    with patch("backend.adapters.spotify.login") as login:
        cli.ensure_spotify_login()
    login.assert_not_called()


def test_ensure_spotify_login_runs_when_missing(tmp_path, monkeypatch) -> None:
    path = tmp_path / "missing.json"
    monkeypatch.setattr(cli, "SPOTIFY_TOKEN_PATH", path)
    with patch("backend.adapters.spotify.login") as login:
        cli.ensure_spotify_login()
    login.assert_called_once_with()
