from unittest.mock import patch

from backend import cli


def test_help_lists_on_off_auth(capsys) -> None:
    cli.main([])
    out = capsys.readouterr().out
    assert "auth" in out
    assert "on" in out
    assert "off" in out
    assert "OpenCode" in out
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


def test_on_dispatches(capsys) -> None:
    with patch("backend.auth_wizard.run_on") as m:
        cli.main(["on"])
    m.assert_called_once_with()


def test_off_dispatches() -> None:
    with patch("backend.auth_wizard.run_off") as m:
        cli.main(["off"])
    m.assert_called_once_with()


def test_tick_writes_line(capsys) -> None:
    with patch("backend.claude.statusline.tick", return_value="♪ x"):
        cli.main(["tick"])
    assert capsys.readouterr().out == "♪ x\n"


def test_tick_json_flag(capsys) -> None:
    with patch(
        "backend.claude.statusline.tick",
        return_value='{"title":"x"}',
    ) as tick:
        cli.main(["tick", "--json"])
    tick.assert_called_once_with(as_json=True)
    assert capsys.readouterr().out.startswith("{")


def test_tick_empty_writes_nothing(capsys) -> None:
    with patch("backend.claude.statusline.tick", return_value=""):
        cli.main(["tick"])
    assert capsys.readouterr().out == ""


def test_auth_dispatches() -> None:
    with patch("backend.auth_wizard.run") as run:
        cli.main(["auth"])
    run.assert_called_once_with()
