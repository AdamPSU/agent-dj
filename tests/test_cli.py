from unittest.mock import patch

from backend import cli


def test_help_lists_on_off_auth(capsys) -> None:
    cli.main([])
    out = capsys.readouterr().out
    assert "auth" in out
    assert "on" in out
    assert "off" in out
    assert "setup" not in out
    assert "jam" not in out
    assert "tick" not in out


def test_unknown_command(capsys) -> None:
    try:
        cli.main(["nope"])
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert exc.code == 2
    err = capsys.readouterr()
    assert "unknown command" in err.err


def test_on_calls_ensure(capsys) -> None:
    with patch(
        "backend.claude.statusline.ensure_installed",
        return_value={"ok": True, "action": "installed"},
    ) as m:
        cli.main(["on"])
    m.assert_called_once()
    assert "installed" in capsys.readouterr().out


def test_off_calls_uninstall(capsys) -> None:
    with patch(
        "backend.claude.statusline.uninstall",
        return_value={"ok": True, "action": "disabled"},
    ) as m:
        cli.main(["off"])
    m.assert_called_once()
    assert "off" in capsys.readouterr().out


def test_tick_writes_line(capsys) -> None:
    with patch("backend.claude.statusline.tick", return_value="♪ x"):
        cli.main(["tick"])
    assert capsys.readouterr().out == "♪ x\n"


def test_tick_empty_writes_nothing(capsys) -> None:
    with patch("backend.claude.statusline.tick", return_value=""):
        cli.main(["tick"])
    assert capsys.readouterr().out == ""


def test_auth_dispatches() -> None:
    with patch("backend.claude.auth.run") as run:
        cli.main(["auth"])
    run.assert_called_once_with()
