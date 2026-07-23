import json
from pathlib import Path
from unittest.mock import patch

from backend.claude import statusline


def test_ensure_installed_writes_tick_command(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    marker = tmp_path / "marker.json"
    settings.write_text("{}")
    out = statusline.ensure_installed(
        settings_path=settings,
        marker_path=marker,
        install_command="/usr/bin/dj tick",
    )
    assert out["ok"] is True
    data = json.loads(settings.read_text())
    assert data["statusLine"]["command"] == "/usr/bin/dj tick"
    assert data["statusLine"]["refreshInterval"] == 0.5
    m = json.loads(marker.read_text())
    assert m["installed_command"] == "/usr/bin/dj tick"
    assert m["previous"] is None


def test_ensure_installed_preserves_previous(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    marker = tmp_path / "marker.json"
    settings.write_text(
        json.dumps(
            {
                "statusLine": {
                    "type": "command",
                    "command": "echo hi",
                    "padding": 2,
                }
            }
        )
    )
    statusline.ensure_installed(
        settings_path=settings,
        marker_path=marker,
        install_command="/usr/bin/dj tick",
    )
    m = json.loads(marker.read_text())
    assert m["previous"]["command"] == "echo hi"
    data = json.loads(settings.read_text())
    assert data["statusLine"]["padding"] == 2


def test_uninstall_restores_previous(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    marker = tmp_path / "marker.json"
    cmd = "/usr/bin/dj tick"
    settings.write_text(
        json.dumps({"statusLine": {"type": "command", "command": cmd}})
    )
    marker.write_text(
        json.dumps(
            {
                "version": 1,
                "installed_command": cmd,
                "previous": {"type": "command", "command": "echo hi"},
            }
        )
    )
    out = statusline.uninstall(settings_path=settings, marker_path=marker)
    assert out["action"] == "disabled"
    data = json.loads(settings.read_text())
    assert data["statusLine"]["command"] == "echo hi"


def test_is_our_command_tick() -> None:
    assert statusline.is_our_command("/usr/bin/dj tick") is True
    assert statusline.is_our_command("python -m backend.cli tick") is True
    assert statusline.is_our_command("echo hi") is False


def test_tick_renders_tracker_line(tmp_path: Path) -> None:
    marker = tmp_path / "marker.json"
    marker.write_text(json.dumps({"previous": None, "installed_command": "x"}))
    cache = tmp_path / "np.json"
    cache.write_text(
        json.dumps(
            {
                "fetched_at": 1000.0,
                "is_playing": True,
                "spotify_id": "x",
                "name": "Baby",
                "artists": "Four Tet",
                "progress_ms": 0,
                "duration_ms": 60_000,
            }
        )
    )
    out = statusline.tick(
        stdin_data=b"",
        marker_path=marker,
        now=1004.0,  # +4s progress; glyph frame 0 → ♪
        fetch=lambda: (_ for _ in ()).throw(AssertionError("no fetch")),
        cache_path=cache,
        color=False,
    )
    assert out == "♪ Four Tet — Baby · 0:04/1:00"


def test_tick_prepends_user_command(tmp_path: Path) -> None:
    marker = tmp_path / "marker.json"
    marker.write_text(
        json.dumps(
            {
                "installed_command": "/usr/bin/dj tick",
                "previous": {"command": "echo USER"},
            }
        )
    )
    cache = tmp_path / "np.json"
    cache.write_text(
        json.dumps(
            {
                "fetched_at": 1000.0,
                "is_playing": False,
                "spotify_id": "x",
                "name": "T",
                "artists": "A",
                "progress_ms": 1000,
                "duration_ms": 5000,
            }
        )
    )
    with patch.object(statusline, "_run_user_command", return_value="USER"):
        out = statusline.tick(
            stdin_data=b"{}",
            marker_path=marker,
            now=1004.0,
            fetch=lambda: None,
            cache_path=cache,
            color=False,
        )
    assert out == "USER\n♪ A — T · 0:01/0:05"
