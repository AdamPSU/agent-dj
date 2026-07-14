import json
from unittest.mock import patch

from backend import cli


def test_status_prints_json(capsys) -> None:
    payload = {"ok": True, "pid": 123}
    with patch.object(cli, "request", return_value=payload):
        cli.main(["status"])
    assert json.loads(capsys.readouterr().out) == payload


def test_play_ensures_login_and_daemon_then_posts(capsys) -> None:
    payload = {"ok": True, "play": "not_implemented"}
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


def test_ensure_spotify_login_uses_ensure_session() -> None:
    with patch("backend.adapters.spotify.ensure_session") as ensure_session:
        cli.ensure_spotify_login()
    ensure_session.assert_called_once_with()
