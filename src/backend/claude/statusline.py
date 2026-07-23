"""Claude Code statusline: preserve user bar, append Spotify tracker when active."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from backend import tracker
from backend.config import APP_DIR

CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
STATUSLINE_MARKER = APP_DIR / "statusline.json"
MARKER_VERSION = 1


def resolve_install_command() -> str:
    exe = Path(sys.executable).resolve()
    sibling = exe.parent / "dj"
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return f"{sibling} tick"
    which = shutil.which("dj")
    if which:
        return f"{Path(which).resolve()} tick"
    return f"{exe} -m backend.cli tick"


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


def is_our_command(command: str | None, *, install_command: str | None = None) -> bool:
    if not isinstance(command, str) or not command.strip():
        return False
    cmd = command.strip()
    ours = (install_command or resolve_install_command()).strip()
    if cmd == ours:
        return True
    if "backend.cli" in cmd and "tick" in cmd:
        return True
    if cmd.endswith(" tick") or " tick" in cmd.split():
        if "/dj" in cmd or cmd.startswith("dj ") or cmd.endswith("/dj tick"):
            return True
    return False


def _safe_previous(
    candidate: Any,
    *,
    install_command: str,
) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    if is_our_command(candidate.get("command"), install_command=install_command):
        return None
    return candidate


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
    settings_path = settings_path or CLAUDE_SETTINGS_PATH
    marker_path = marker_path or STATUSLINE_MARKER
    cmd = install_command or resolve_install_command()
    try:
        settings = _read_json(settings_path) or {}
        current = settings.get("statusLine")
        if not isinstance(current, dict):
            current = None

        marker_existing = load_marker(marker_path) or {}
        if marker_existing.get("installed_command"):
            previous = _safe_previous(
                marker_existing.get("previous"), install_command=cmd
            )
        else:
            previous = _safe_previous(current, install_command=cmd)

        already = (
            isinstance(current, dict)
            and current.get("command") == cmd
            and marker_existing.get("installed_command") == cmd
        )
        if already:
            fixed = _safe_previous(marker_existing.get("previous"), install_command=cmd)
            if marker_existing.get("previous") != fixed:
                marker_existing["previous"] = fixed
                _write_json(marker_path, marker_existing)
            return {"ok": True, "action": "noop", "enabled": True, "command": cmd}

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
        if isinstance(previous, dict) and "padding" in previous:
            new_sl["padding"] = previous["padding"]
        elif isinstance(current, dict) and "padding" in current:
            new_sl["padding"] = current["padding"]
        settings["statusLine"] = new_sl
        _write_json(settings_path, settings)
        action = "updated" if marker_existing.get("installed_command") else "installed"
        return {"ok": True, "action": action, "enabled": True, "command": cmd}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def uninstall(
    *,
    settings_path: Path | None = None,
    marker_path: Path | None = None,
) -> dict[str, Any]:
    settings_path = settings_path or CLAUDE_SETTINGS_PATH
    marker_path = marker_path or STATUSLINE_MARKER
    try:
        if not is_installed(settings_path=settings_path, marker_path=marker_path):
            return {"ok": True, "action": "noop", "enabled": False}

        marker = load_marker(marker_path) or {}
        cmd = str(marker.get("installed_command") or resolve_install_command())
        previous = _safe_previous(marker.get("previous"), install_command=cmd)
        settings = _read_json(settings_path) or {}
        if isinstance(previous, dict):
            settings["statusLine"] = previous
        else:
            settings.pop("statusLine", None)
        _write_json(settings_path, settings)
        marker["previous"] = previous
        _write_json(marker_path, marker)
        return {"ok": True, "action": "disabled", "enabled": False}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


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


def tick(
    *,
    stdin_data: bytes | None = None,
    settings_path: Path | None = None,
    marker_path: Path | None = None,
    now: float | None = None,
    fetch=None,
    cache_path: Path | None = None,
    color: bool | None = None,
) -> str:
    if stdin_data is None:
        stdin_data = sys.stdin.buffer.read() if not sys.stdin.isatty() else b""

    lines: list[str] = []
    marker = load_marker(marker_path)
    previous = marker.get("previous") if marker else None
    user_cmd = None
    if isinstance(previous, dict):
        user_cmd = previous.get("command")
    if isinstance(user_cmd, str) and user_cmd.strip() and not is_our_command(user_cmd):
        user_out = _run_user_command(user_cmd, stdin_data)
        if user_out:
            lines.append(user_out)

    snap = tracker.resolve_snapshot(now=now, fetch=fetch, cache_path=cache_path)
    dj = tracker.render_snapshot(snap, color=color, now=now)
    if dj:
        lines.append(dj)

    return "\n".join(lines)
