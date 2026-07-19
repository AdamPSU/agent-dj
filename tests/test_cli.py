from unittest.mock import patch

from claude_dj import cli


def test_help_default_and_explicit(capsys) -> None:
    cli.main([])
    out = capsys.readouterr().out
    assert "jam" in out
    assert "kill" in out
    assert "device" in out
    assert "device [id]" not in out
    assert "  statusline" not in out

    cli.main(["help"])
    assert "jam" in capsys.readouterr().out


def test_unknown_command_shows_help(capsys) -> None:
    try:
        cli.main(["nope"])
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert exc.code == 2
    err = capsys.readouterr()
    assert "unknown command" in err.err
    assert "jam" in err.out


def test_jam_success_prints_enjoy(capsys) -> None:
    payload = {"ok": True, "size": 12, "source": "random"}
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
    captured = capsys.readouterr()
    assert captured.out.strip() == "enjoy!"
    assert captured.err == ""


def test_jam_resumed_prints_joined(capsys) -> None:
    payload = {"ok": True, "resumed": True}
    with (
        patch("claude_dj.integrate.statusline.ensure_installed"),
        patch.object(cli, "ensure_spotify_login"),
        patch.object(cli, "ensure_daemon"),
        patch.object(cli, "request", return_value=payload),
    ):
        cli.main(["jam"])
    assert capsys.readouterr().out.strip() == "joined existing session."


def test_jam_waiting_prints_sync_message_exit_zero(capsys) -> None:
    payload = {
        "ok": True,
        "waiting": True,
        "indexed": 0,
        "catalog_total": 720,
    }
    with (
        patch("claude_dj.integrate.statusline.ensure_installed"),
        patch.object(cli, "ensure_spotify_login"),
        patch.object(cli, "ensure_daemon"),
        patch.object(cli, "request", return_value=payload),
    ):
        cli.main(["jam"])
    captured = capsys.readouterr()
    assert (
        captured.out.strip()
        == "your songs are being synced. please wait; the jam will start shortly."
    )
    assert captured.err == ""


def test_jam_hard_failure_exits_nonzero(capsys) -> None:
    payload = {
        "ok": False,
        "error": "play_failed",
        "detail": "no active device",
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
    assert captured.out == ""
    assert "couldn't start: no active device" in captured.err


def test_kill_prints_goodbye(capsys) -> None:
    with (
        patch("claude_dj.integrate.statusline.uninstall") as uninstall,
        patch.object(cli, "reachable", return_value=True),
        patch.object(cli, "request", return_value={"ok": True}) as request,
    ):
        cli.main(["kill"])
    uninstall.assert_called_once_with()
    request.assert_called_once_with("POST", "/kill")
    assert capsys.readouterr().out.strip() == "goodbye!"


def test_kill_when_daemon_down_still_goodbye(capsys) -> None:
    with (
        patch("claude_dj.integrate.statusline.uninstall") as uninstall,
        patch.object(cli, "reachable", return_value=False),
    ):
        cli.main(["kill"])
    uninstall.assert_called_once_with()
    assert capsys.readouterr().out.strip() == "goodbye!"


def test_statusline_bare_is_unknown(capsys) -> None:
    try:
        cli.main(["statusline"])
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert exc.code == 2
    assert "unknown command" in capsys.readouterr().err


def test_statusline_render_flag(capsys) -> None:
    with patch(
        "claude_dj.integrate.statusline.run",
        return_value="♪ Four Tet — Baby · 0:01/0:02",
    ) as run:
        cli.main(["statusline", "--render"])
    run.assert_called_once_with()
    assert "Four Tet" in capsys.readouterr().out


def test_sync_started(capsys) -> None:
    with (
        patch.object(cli, "reachable", return_value=True),
        patch.object(cli, "request", return_value={"ok": True, "syncing": True}) as request,
    ):
        cli.main(["sync"])
    request.assert_called_once_with("POST", "/sync")
    assert capsys.readouterr().out.strip() == "finding new songs."


def test_sync_already_running(capsys) -> None:
    # kick() returns False when already running; daemon still reports syncing.
    with (
        patch.object(cli, "reachable", return_value=True),
        patch.object(
            cli,
            "request",
            return_value={"ok": True, "syncing": True, "already": True},
        ),
    ):
        cli.main(["sync"])
    assert capsys.readouterr().out.strip() == "sync already in progress."


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


def test_device_list_plain(capsys) -> None:
    payload = {
        "ok": True,
        "devices": [
            {
                "id": "dev1",
                "name": "Living Room",
                "type": "Speaker",
                "is_active": True,
            },
            {
                "id": "dev2",
                "name": "Phone",
                "type": "Smartphone",
                "is_active": False,
            },
        ],
        "preferred_device_id": "dev1",
    }
    with (
        patch.object(cli, "ensure_spotify_login") as login,
        patch.object(cli, "ensure_daemon") as ensure,
        patch.object(cli, "request", return_value=payload) as request,
    ):
        cli.main(["device"])
    login.assert_called_once_with()
    ensure.assert_called_once_with()
    request.assert_called_once_with("GET", "/devices")
    out = capsys.readouterr().out
    assert "* Living Room (dev1)" in out
    assert "  Phone (dev2)" in out


def test_device_list_empty(capsys) -> None:
    payload = {"ok": True, "devices": [], "preferred_device_id": None}
    with (
        patch.object(cli, "ensure_spotify_login"),
        patch.object(cli, "ensure_daemon"),
        patch.object(cli, "request", return_value=payload),
    ):
        cli.main(["device"])
    assert capsys.readouterr().out.strip() == "no devices online."


def test_device_id_arg_is_unknown(capsys) -> None:
    try:
        cli.main(["device", "dev1"])
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert exc.code == 2
    assert "unknown command" in capsys.readouterr().err


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
