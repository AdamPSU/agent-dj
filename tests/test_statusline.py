import json
from pathlib import Path

from claude_dj.integrate import statusline


def test_format_ms() -> None:
    assert statusline.format_ms(0) == "0:00"
    assert statusline.format_ms(102_000) == "1:42"
    assert statusline.format_ms(190_000) == "3:10"
    assert statusline.format_ms(3_661_000) == "1:01:01"
    assert statusline.format_ms(None) == "--:--"


def test_format_playing_only_no_color() -> None:
    line = statusline.format_line(
        {
            "mode": "attached",
            "syncing": False,
            "indexed": 10,
            "catalog_total": 10,
            "now_playing": {
                "name": "Baby",
                "artists": "Four Tet",
                "progress_ms": 102_000,
                "duration_ms": 190_000,
            },
        },
        color=False,
        now=0.0,  # glyph frame 0 → ♪
    )
    assert line == "♪ Four Tet — Baby · 1:42/3:10"


def test_music_glyph_cycles_each_second() -> None:
    assert statusline.music_glyph(now=0.0) == "♪"
    assert statusline.music_glyph(now=1.0) == "♫"
    assert statusline.music_glyph(now=2.0) == "♬"
    assert statusline.music_glyph(now=3.0) == "♩"
    assert statusline.music_glyph(now=4.0) == "♪"


def test_format_glyph_follows_now() -> None:
    payload = {
        "mode": "attached",
        "syncing": False,
        "indexed": 1,
        "catalog_total": 1,
        "now_playing": {
            "name": "Baby",
            "artists": "Four Tet",
            "progress_ms": 0,
            "duration_ms": 1000,
        },
    }
    assert statusline.format_line(payload, color=False, now=1.0).startswith("♫ ")
    assert statusline.format_line(payload, color=False, now=2.0).startswith("♬ ")


def test_format_playing_plus_sync() -> None:
    line = statusline.format_line(
        {
            "mode": "attached",
            "syncing": True,
            "indexed": 128,
            "catalog_total": 900,
            "now_playing": {
                "name": "Baby",
                "artists": "Four Tet",
                "progress_ms": 102_000,
                "duration_ms": 190_000,
            },
        },
        color=False,
        now=0.0,
    )
    assert line == "♪ Four Tet — Baby · 1:42/3:10 · ⠋ sync: 128/900 songs"


def test_format_sync_only() -> None:
    line = statusline.format_line(
        {
            "mode": "idle",
            "syncing": True,
            "indexed": 128,
            "catalog_total": 900,
            "now_playing": None,
        },
        color=False,
        now=0.0,
    )
    assert line == "⠋ sync: 128/900 songs"


def test_sync_glyph_cycles() -> None:
    assert statusline.sync_glyph(now=0.0) == "⠋"
    assert statusline.sync_glyph(now=1.0) == "⠙"
    assert statusline.sync_glyph(now=9.0) == "⠏"
    assert statusline.sync_glyph(now=10.0) == "⠋"


def test_format_hidden_when_idle_and_not_syncing() -> None:
    assert (
        statusline.format_line(
            {
                "mode": "idle",
                "syncing": False,
                "indexed": 10,
                "catalog_total": 10,
                "now_playing": None,
            },
            color=False,
        )
        == ""
    )


def test_format_idle_spotify_playback() -> None:
    line = statusline.format_line(
        {
            "mode": "idle",
            "syncing": False,
            "indexed": 10,
            "catalog_total": 10,
            "now_playing": {
                "name": "Baby",
                "artists": "Four Tet",
                "progress_ms": 102_000,
                "duration_ms": 190_000,
                "spotify_id": "abc",
            },
        },
        color=False,
        now=0.0,
    )
    assert line == "♪ Four Tet — Baby · 1:42/3:10"


def test_format_hidden_when_sync_complete() -> None:
    assert (
        statusline.format_line(
            {
                "mode": "idle",
                "syncing": True,
                "indexed": 900,
                "catalog_total": 900,
                "now_playing": None,
            },
            color=False,
        )
        == ""
    )


def test_format_uses_spotify_green_when_color() -> None:
    line = statusline.format_line(
        {
            "mode": "attached",
            "syncing": False,
            "indexed": 1,
            "catalog_total": 1,
            "now_playing": {
                "name": "Baby",
                "artists": "Four Tet",
                "progress_ms": 0,
                "duration_ms": 1000,
            },
        },
        color=True,
    )
    assert "\033[38;2;29;185;84m" in line  # note #1DB954
    assert "\033[38;2;168;219;184m" in line  # title sage #A8DBB8
    assert "\033[38;2;30;215;96m" in line  # time #1ED760


def test_ensure_installed_wraps_and_is_idempotent(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    marker = tmp_path / "statusline.json"
    settings.write_text(
        json.dumps(
            {
                "statusLine": {
                    "type": "command",
                    "command": "bash /tmp/old.sh",
                    "padding": 2,
                }
            }
        ),
        encoding="utf-8",
    )
    cmd = "/abs/dj statusline --render"
    out = statusline.ensure_installed(
        settings_path=settings,
        marker_path=marker,
        install_command=cmd,
    )
    assert out["action"] == "installed"
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == cmd
    assert data["statusLine"]["refreshInterval"] == 1
    assert data["statusLine"]["padding"] == 2
    mark = json.loads(marker.read_text(encoding="utf-8"))
    assert mark["previous"]["command"] == "bash /tmp/old.sh"
    assert statusline.is_installed(settings_path=settings, marker_path=marker)

    again = statusline.ensure_installed(
        settings_path=settings,
        marker_path=marker,
        install_command=cmd,
    )
    assert again["action"] == "noop"


def test_run_appends_dj_under_user(monkeypatch, tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    marker = tmp_path / "statusline.json"
    marker.write_text(
        json.dumps(
            {
                "version": 1,
                "installed_command": "x statusline",
                "previous": {"type": "command", "command": "printf 'user-line'"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        statusline,
        "fetch_status",
        lambda **k: {
            "mode": "attached",
            "syncing": False,
            "indexed": 1,
            "catalog_total": 1,
            "now_playing": {
                "name": "Baby",
                "artists": "Four Tet",
                "progress_ms": 1000,
                "duration_ms": 2000,
            },
        },
    )
    monkeypatch.setenv("NO_COLOR", "1")
    out = statusline.run(
        stdin_data=b"{}",
        settings_path=settings,
        marker_path=marker,
    )
    assert out.splitlines()[0] == "user-line"
    dj = out.splitlines()[1]
    assert dj[0] in statusline._MUSIC_GLYPHS
    assert "Four Tet — Baby" in dj
    assert "0:01/0:02" in dj


def test_jam_auto_installs_statusline(monkeypatch, capsys) -> None:
    from claude_dj import cli

    called: list[int] = []

    def fake_ensure(**k):
        called.append(1)
        return {"ok": True, "action": "installed"}

    with monkeypatch.context() as m:
        m.setattr("claude_dj.integrate.statusline.ensure_installed", fake_ensure)
        m.setattr(cli, "ensure_spotify_login", lambda: None)
        m.setattr(cli, "ensure_daemon", lambda: None)
        m.setattr(cli, "request", lambda *a, **k: {"ok": True})
        cli.main(["jam"])
    assert called == [1]
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_ensure_installed_never_saves_self_as_previous(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    marker = tmp_path / "statusline.json"
    cmd = "/abs/dj statusline --render"
    # Broken state: settings already point at us, no real previous.
    settings.write_text(
        json.dumps({"statusLine": {"type": "command", "command": cmd}}),
        encoding="utf-8",
    )
    out = statusline.ensure_installed(
        settings_path=settings,
        marker_path=marker,
        install_command=cmd,
    )
    assert out["action"] == "installed"
    mark = json.loads(marker.read_text(encoding="utf-8"))
    assert mark["previous"] is None


def test_run_skips_self_referential_previous(monkeypatch, tmp_path: Path) -> None:
    marker = tmp_path / "statusline.json"
    cmd = "/abs/dj statusline --render"
    marker.write_text(
        json.dumps(
            {
                "version": 1,
                "installed_command": cmd,
                "previous": {"type": "command", "command": cmd},
            }
        ),
        encoding="utf-8",
    )
    called: list[str] = []

    def boom(command: str, stdin_data: bytes) -> str:
        called.append(command)
        return "should-not-run"

    monkeypatch.setattr(statusline, "_run_user_command", boom)
    monkeypatch.setattr(
        statusline,
        "fetch_status",
        lambda **k: {
            "mode": "idle",
            "syncing": True,
            "indexed": 1,
            "catalog_total": 10,
            "now_playing": None,
        },
    )
    monkeypatch.setenv("NO_COLOR", "1")
    out = statusline.run(stdin_data=b"{}", marker_path=marker)
    assert called == []
    assert "sync:" in out


def test_ensure_installed_repairs_self_previous_on_noop(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    marker = tmp_path / "statusline.json"
    cmd = "/abs/dj statusline --render"
    settings.write_text(
        json.dumps({"statusLine": {"type": "command", "command": cmd}}),
        encoding="utf-8",
    )
    marker.write_text(
        json.dumps(
            {
                "version": 1,
                "installed_command": cmd,
                "previous": {"type": "command", "command": cmd},
            }
        ),
        encoding="utf-8",
    )
    out = statusline.ensure_installed(
        settings_path=settings,
        marker_path=marker,
        install_command=cmd,
    )
    assert out["action"] == "noop"
    mark = json.loads(marker.read_text(encoding="utf-8"))
    assert mark["previous"] is None


def test_toggle_enable_then_disable(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    marker = tmp_path / "statusline.json"
    settings.write_text(
        json.dumps(
            {
                "statusLine": {
                    "type": "command",
                    "command": "bash /tmp/old.sh",
                    "padding": 2,
                }
            }
        ),
        encoding="utf-8",
    )
    cmd = "/abs/dj statusline --render"
    on = statusline.toggle(
        settings_path=settings,
        marker_path=marker,
        install_command=cmd,
    )
    assert on["enabled"] is True
    assert on["action"] == "installed"
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == cmd

    off = statusline.toggle(
        settings_path=settings,
        marker_path=marker,
        install_command=cmd,
    )
    assert off["enabled"] is False
    assert off["action"] == "disabled"
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == "bash /tmp/old.sh"
    assert data["statusLine"]["padding"] == 2

    # Re-enable keeps original previous
    on2 = statusline.toggle(
        settings_path=settings,
        marker_path=marker,
        install_command=cmd,
    )
    assert on2["enabled"] is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == cmd
    mark = json.loads(marker.read_text(encoding="utf-8"))
    assert mark["previous"]["command"] == "bash /tmp/old.sh"
