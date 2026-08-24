from unittest.mock import patch

from backend import cli


def test_help_lists_on_off_auth(capsys) -> None:
    cli.main([])
    out = capsys.readouterr().out
    assert "auth" in out
    assert "on" in out
    assert "off" in out
    assert "OpenCode" in out
    assert "Pi" in out
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


def test_help_lists_palette(capsys) -> None:
    cli.main(["help"])
    assert "palette" in capsys.readouterr().out


def test_palette_show(capsys, monkeypatch, tmp_path) -> None:
    from backend import config

    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    cli.main(["palette"])
    out = capsys.readouterr().out
    assert "#888888" in out
    assert "#C1C1C1" in out
    assert "#486E6F" in out


def test_palette_set(capsys, monkeypatch, tmp_path) -> None:
    from backend import config

    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    with patch("backend.opencode.statusline.write_runtime_config"):
        cli.main(["palette", "#f00", "#0f0", "#00f"])
    assert config.load_palette() == ("#FF0000", "#00FF00", "#0000FF")
    assert "FF0000" in capsys.readouterr().out


def test_help_lists_placement(capsys) -> None:
    cli.main(["help"])
    assert "placement" in capsys.readouterr().out


def test_placement_show(capsys, monkeypatch, tmp_path) -> None:
    from backend import config

    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    cli.main(["placement"])
    assert "below" in capsys.readouterr().out


def test_placement_set(capsys, monkeypatch, tmp_path) -> None:
    from backend import config

    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    with patch("backend.pi.statusline.write_runtime_config"):
        cli.main(["placement", "above"])
    assert config.load_pi_placement() == "above"
    assert "above" in capsys.readouterr().out
