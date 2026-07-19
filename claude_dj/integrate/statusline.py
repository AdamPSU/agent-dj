"""Claude Code statusline wrapper: preserve user bar, append DJ line when active."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from claude_dj.config import BASE_URL, CLAUDE_SETTINGS_PATH, STATUSLINE_MARKER

# /status may hit Spotify for progress; keep under refreshInterval (1s).
STATUS_TIMEOUT_S = 0.8
MARKER_VERSION = 1

# One frame per statusline refresh (~1s).
_MUSIC_GLYPHS = ("♪", "♫", "♬", "♩")
_SYNC_GLYPHS = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

# Spotify green family — title is soft sage (not white, not gray)
_NOTE = "\033[38;2;29;185;84m"  # 1DB954
_TITLE = "\033[38;2;168;219;184m"  # A8DBB8 soft sage
_DIM = "\033[38;2;108;112;134m"  # 6C7086
_TIME = "\033[38;2;30;215;96m"  # 1ED760
_COUNT = "\033[38;2;167;167;167m"  # A7A7A7
_RESET = "\033[0m"


def music_glyph(*, now: float | None = None) -> str:
    """Cycle music symbol once per second."""
    t = time.time() if now is None else now
    return _MUSIC_GLYPHS[int(t) % len(_MUSIC_GLYPHS)]


def sync_glyph(*, now: float | None = None) -> str:
    """Cycle braille spinner once per second while catalog sync has work."""
    t = time.time() if now is None else now
    return _SYNC_GLYPHS[int(t) % len(_SYNC_GLYPHS)]


def _use_color() -> bool:
    return not os.environ.get("NO_COLOR")


def _c(code: str, text: str, *, color: bool) -> str:
    if not color:
        return text
    return f"{code}{text}{_RESET}"


def format_ms(ms: int | None) -> str:
    """Format milliseconds as m:ss (or h:mm:ss if >= 1h)."""
    if ms is None:
        return "--:--"
    total = max(0, int(ms) // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def sync_work_visible(syncing: bool, indexed: int, catalog_total: int) -> bool:
    return bool(syncing) and int(indexed) < int(catalog_total)


def should_show_line(payload: dict[str, Any]) -> bool:
    mode = payload.get("mode")
    np = payload.get("now_playing")
    playing = mode == "attached" and isinstance(np, dict)
    syncing = sync_work_visible(
        bool(payload.get("syncing")),
        int(payload.get("indexed") or 0),
        int(payload.get("catalog_total") or 0),
    )
    return playing or syncing


def format_line(
    payload: dict[str, Any],
    *,
    color: bool | None = None,
    now: float | None = None,
) -> str:
    """Render the DJ statusline row, or empty string when nothing to show."""
    if color is None:
        color = _use_color()
    if not should_show_line(payload):
        return ""

    parts: list[str] = []
    mode = payload.get("mode")
    np = payload.get("now_playing")
    if mode == "attached" and isinstance(np, dict):
        artists = str(np.get("artists") or "").strip() or "unknown"
        name = str(np.get("name") or "").strip() or "unknown"
        prog = format_ms(np.get("progress_ms") if np.get("progress_ms") is not None else None)
        dur = format_ms(np.get("duration_ms") if np.get("duration_ms") is not None else None)
        title = f"{artists} — {name}"
        glyph = music_glyph(now=now)
        parts.append(
            f"{_c(_NOTE, glyph, color=color)} "
            f"{_c(_TITLE, title, color=color)} "
            f"{_c(_DIM, '·', color=color)} "
            f"{_c(_TIME, f'{prog}/{dur}', color=color)}"
        )

    if sync_work_visible(
        bool(payload.get("syncing")),
        int(payload.get("indexed") or 0),
        int(payload.get("catalog_total") or 0),
    ):
        i = int(payload.get("indexed") or 0)
        n = int(payload.get("catalog_total") or 0)
        spin = sync_glyph(now=now)
        sync_seg = (
            f"{_c(_NOTE, spin, color=color)} "
            f"{_c(_DIM, 'sync:', color=color)} "
            f"{_c(_COUNT, f'{i}/{n}', color=color)} "
            f"{_c(_DIM, 'songs', color=color)}"
        )
        if parts:
            parts.append(f"{_c(_DIM, '·', color=color)} {sync_seg}")
        else:
            parts.append(sync_seg)

    return " ".join(parts)


def resolve_install_command() -> str:
    """Absolute command string written into Claude Code settings."""
    exe = Path(sys.executable).resolve()
    sibling = exe.parent / "claude-dj"
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return f"{sibling} statusline"
    which = shutil.which("claude-dj")
    if which:
        return f"{Path(which).resolve()} statusline"
    return f"{exe} -m claude_dj.cli statusline"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_marker(path: Path | None = None) -> dict[str, Any] | None:
    return _read_json(path or STATUSLINE_MARKER)


def is_installed(
    *,
    settings_path: Path | None = None,
    marker_path: Path | None = None,
) -> bool:
    marker = load_marker(marker_path)
    if not marker:
        return False
    installed = marker.get("installed_command")
    if not isinstance(installed, str) or not installed:
        return False
    settings = _read_json(settings_path or CLAUDE_SETTINGS_PATH) or {}
    sl = settings.get("statusLine")
    if not isinstance(sl, dict):
        return False
    return sl.get("command") == installed


def ensure_installed(
    *,
    settings_path: Path | None = None,
    marker_path: Path | None = None,
    install_command: str | None = None,
) -> dict[str, Any]:
    """Wrap Claude Code statusLine if not already ours. Best-effort, never raises."""
    settings_path = settings_path or CLAUDE_SETTINGS_PATH
    marker_path = marker_path or STATUSLINE_MARKER
    cmd = install_command or resolve_install_command()
    try:
        if is_installed(settings_path=settings_path, marker_path=marker_path):
            return {"ok": True, "action": "noop"}

        settings = _read_json(settings_path) or {}
        previous = settings.get("statusLine")
        if not isinstance(previous, dict):
            previous = None

        marker = {
            "version": MARKER_VERSION,
            "installed_command": cmd,
            "previous": previous,
        }
        _write_json(marker_path, marker)

        new_sl: dict[str, Any] = {
            "type": "command",
            "command": cmd,
            "refreshInterval": 1,
        }
        if previous and "padding" in previous:
            new_sl["padding"] = previous["padding"]
        settings["statusLine"] = new_sl
        _write_json(settings_path, settings)
        return {"ok": True, "action": "installed", "command": cmd}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def uninstall(
    *,
    settings_path: Path | None = None,
    marker_path: Path | None = None,
) -> dict[str, Any]:
    """Restore previous statusLine if we still own it."""
    settings_path = settings_path or CLAUDE_SETTINGS_PATH
    marker_path = marker_path or STATUSLINE_MARKER
    marker = load_marker(marker_path)
    if not marker:
        return {"ok": True, "action": "noop", "detail": "no marker"}

    settings = _read_json(settings_path) or {}
    sl = settings.get("statusLine")
    owned = isinstance(sl, dict) and sl.get("command") == marker.get("installed_command")
    if owned:
        previous = marker.get("previous")
        if isinstance(previous, dict):
            settings["statusLine"] = previous
        else:
            settings.pop("statusLine", None)
        _write_json(settings_path, settings)
        action = "restored"
    else:
        action = "marker_only"

    try:
        marker_path.unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True, "action": action}


def fetch_status(*, base_url: str = BASE_URL, timeout: float = STATUS_TIMEOUT_S) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(f"{base_url}/status", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return data if isinstance(data, dict) else None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _run_user_command(command: str, stdin_data: bytes) -> str:
    try:
        proc = subprocess.run(
            command,
            input=stdin_data,
            capture_output=True,
            shell=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    out = proc.stdout.decode(errors="replace") if proc.stdout else ""
    return out.rstrip("\n")


def run(
    *,
    stdin_data: bytes | None = None,
    settings_path: Path | None = None,
    marker_path: Path | None = None,
    base_url: str = BASE_URL,
) -> str:
    """Produce full statusline stdout (user lines + optional DJ line)."""
    if stdin_data is None:
        stdin_data = sys.stdin.buffer.read()

    lines: list[str] = []
    marker = load_marker(marker_path)
    previous = marker.get("previous") if marker else None
    user_cmd = None
    if isinstance(previous, dict):
        user_cmd = previous.get("command")
    if isinstance(user_cmd, str) and user_cmd.strip():
        user_out = _run_user_command(user_cmd, stdin_data)
        if user_out:
            lines.append(user_out)

    payload = fetch_status(base_url=base_url)
    if payload:
        dj = format_line(payload)
        if dj:
            lines.append(dj)

    return "\n".join(lines)
