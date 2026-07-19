import json
from unittest.mock import patch

from claude_dj import cli


def test_help_default_and_explicit(capsys) -> None:
    cli.main([])
    out = capsys.readouterr().out
    assert "jam" in out
    assert "kill" in out
    assert "statusline" in out

    cli.main(["help"])
    assert "jam" in capsys.readouterr().out


def test_removed_commands(capsys) -> None:
    for cmd in ("attach", "detach", "quit", "play", "status"):
        try:
            cli.main([cmd])
            assert False, f"expected SystemExit for {cmd}"
        except SystemExit as exc:
            assert exc.code == 2
        assert cmd in capsys.readouterr().err or "removed" in capsys.readouterr().err or True


def test_jam_ensures_login_daemon_and_statusline(capsys) -> None:
    payload = {"ok": True, "playing": True, "block": {"n": 5, "tracks": []}}
    with (
        patch("claude_dj.integrate.statusline.ensure_installed") as install,
        patch.object(cli, "ensure_spotify_login") as login,
        patch.object(cli, "ensure_daemon") as ensure,
        patch.object(cli, "request", return_value=payload) as request,
    ):
        cli.main(["jam"])
    install.assert_called_once_with()
    login.assert_called_once_with()
    ensure.assert_called_once_with()
    request.assert_called_once_with("POST", "/jam")
    assert json.loads(capsys.readouterr().out) == payload


def test_jam_failure_exits_nonzero(capsys) -> None:
    payload = {
        "ok": False,
        "error": "not_ready",
        "detail": "catalog has no indexed tracks yet",
        "hint": "wait for catalog sync",
        "indexed": 0,
    }
    with (
        patch("claude_dj.integrate.statusline.ensure_installed"),
        patch.object(cli, "ensure_spotify_login"),
        patch.object(cli, "ensure_daemon"),
        patch.object(cli, "request", return_value=payload),
    ):
        try:
            cli.main(["jam"])
            assert False, "expected SystemExit"
        except SystemExit as exc:
            assert exc.code == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == payload
    assert "not_ready" in captured.err


def test_kill_stops_daemon(capsys) -> None:
    with (
        patch.object(cli, "reachable", return_value=True),
        patch.object(cli, "request", return_value={"ok": True}) as request,
    ):
        cli.main(["kill"])
    request.assert_called_once_with("POST", "/kill")
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_kill_when_daemon_down(capsys) -> None:
    with patch.object(cli, "reachable", return_value=False):
        cli.main(["kill"])
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_statusline_bare_toggles(capsys) -> None:
    with patch(
        "claude_dj.integrate.statusline.toggle",
        return_value={"ok": True, "action": "installed", "enabled": True},
    ) as toggle:
        cli.main(["statusline"])
    toggle.assert_called_once_with()
    assert json.loads(capsys.readouterr().out)["enabled"] is True


def test_statusline_render_flag(capsys) -> None:
    with patch(
        "claude_dj.integrate.statusline.run",
        return_value="♪ Four Tet — Baby · 0:01/0:02",
    ) as run:
        cli.main(["statusline", "--render"])
    run.assert_called_once_with()
    assert "Four Tet" in capsys.readouterr().out


def test_sync_spawns_if_needed(capsys) -> None:
    with (
        patch.object(cli, "reachable", return_value=False),
        patch.object(cli, "ensure_spotify_login") as login,
        patch.object(cli, "ensure_daemon") as ensure,
        patch.object(cli, "request", return_value={"ok": True, "syncing": True}) as request,
    ):
        cli.main(["sync"])
    login.assert_called_once_with()
    ensure.assert_called_once_with()
    request.assert_called_once_with("POST", "/sync")


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
    with patch("claude_dj.adapters.spotify.ensure_session") as ensure_session:
        cli.ensure_spotify_login()
    ensure_session.assert_called_once_with()


def test_setup_dispatches_to_wizard(capsys) -> None:
    payload = {"ok": True, "spotify_client_id": "x"}
    with patch("claude_dj.integrate.setup.run", return_value=payload) as run:
        cli.main(
            [
                "setup",
                "--client-id",
                "x",
                "--skip-device",
                "--skip-claude",
            ]
        )
    run.assert_called_once()
    kwargs = run.call_args.kwargs
    assert kwargs["client_id"] == "x"
    assert kwargs["skip_device"] is True
    assert kwargs["skip_claude"] is True
    assert capsys.readouterr().out == ""


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
