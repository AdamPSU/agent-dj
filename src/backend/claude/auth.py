"""Interactive Spotify auth for Claude Code statusline."""

from __future__ import annotations

import sys
from typing import Any

from beaupy import Config, confirm, prompt
from rich.console import Console

from backend import config, spotify
from backend.claude import statusline

_NOTE = "#1DB954"
_TITLE = "#A8DBB8"
_DIM = "#6C7086"
_TIME = "#1ED760"
_COUNT = "#A7A7A7"

Config.raise_on_interrupt = True
console = Console(stderr=True)


def _m(style: str, text: str) -> str:
    return f"[{style}]{text}[/{style}]"


def _bind_tty() -> None:
    if sys.stdin.isatty():
        return
    try:
        sys.stdin = open("/dev/tty", encoding="utf-8")  # noqa: SIM115
    except OSError:
        print(
            "dj auth requires an interactive terminal.\nRun: dj auth",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    if not sys.stdin.isatty():
        print(
            "dj auth requires an interactive terminal.\nRun: dj auth",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _resolve_client_id() -> str:
    existing = ""
    try:
        existing = config.resolve_spotify_client_id()
    except config.ConfigError:
        existing = str(config.load_app_config().get("spotify_client_id") or "").strip()

    if existing:
        if confirm(
            f"Use existing Spotify Client ID ({existing[:8]}…)?",
            default_is_yes=True,
        ):
            return existing

    cid = prompt(
        "Spotify Client ID",
        initial_value=existing,
        validator=lambda s: bool(str(s).strip()),
    )
    if cid is None:
        raise SystemExit("auth cancelled")
    cid = str(cid).strip()
    config.set_spotify_client_id(cid)
    return cid


def _spotify_login() -> None:
    already = False
    try:
        already = spotify.session_is_valid()
    except Exception:
        already = False

    if already:
        if not confirm(
            "Spotify is already logged in. Re-authenticate anyway?",
            default_is_yes=False,
        ):
            console.print(_m(_DIM, "Spotify: keeping existing session."))
            return

    if not confirm(
        "Open your browser to authorize Spotify? (required)",
        default_is_yes=True,
    ):
        print("auth cancelled: Spotify login is required", file=sys.stderr)
        raise SystemExit(1)

    console.print(_m(_TITLE, "Spotify login…"))
    spotify.ensure_session()
    console.print(_m(_TIME, "Logged in."))


def run() -> dict[str, Any]:
    _bind_tty()

    console.print(_m(f"bold {_NOTE}", "Claude DJ auth"))
    console.print(_m(_DIM, "--------------"))
    console.print(
        f"{_m(_DIM, 'This enables the Claude Code statusline automatically.')}"
    )
    console.print()

    try:
        cid = _resolve_client_id()
        _spotify_login()

        console.print(_m(f"bold {_TITLE}", "Statusline"))
        statusline_out = statusline.ensure_installed()
        if not statusline_out.get("ok"):
            err = statusline_out.get("error") or "failed"
            print(f"statusline enable failed: {err}", file=sys.stderr)
            raise SystemExit(1)
        console.print(
            f"  {_m(_NOTE, 'on')} {_m(_DIM, '·')} "
            f"{_m(_COUNT, 'enabled automatically')}"
        )
    except KeyboardInterrupt:
        print(file=sys.stderr)
        raise SystemExit("auth cancelled") from None

    console.print()
    console.print(
        f"{_m(f'bold {_TIME}', 'Done.')} "
        f"{_m(_DIM, 'Statusline is on.')} "
        f"{_m(_DIM, 'Toggle later with')} {_m(_NOTE, 'dj off')} "
        f"{_m(_DIM, '/')} {_m(_NOTE, 'dj on')}."
    )
    return {
        "ok": True,
        "spotify_client_id": cid,
        "statusline": statusline_out,
    }
