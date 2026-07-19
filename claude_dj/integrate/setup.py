"""Interactive setup wizard for Claude DJ (TTY required)."""

from __future__ import annotations

import sys
from typing import Any

from beaupy import Config, confirm, prompt, select
from beaupy.spinners import DOTS, Spinner
from rich.console import Console

from claude_dj import config
from claude_dj.adapters import spotify
from claude_dj.integrate import claude_code

Config.raise_on_interrupt = True
console = Console(stderr=True)


def device_label(row: dict[str, Any]) -> str:
    """Human label for a Spotify Connect device row."""
    name = str(row.get("name") or "Unknown")
    kind = str(row.get("type") or "Device")
    base = f"{name} ({kind})"
    if row.get("is_active"):
        return f"{base} · active"
    return base


def _bind_tty() -> None:
    """Point stdin at the controlling TTY (works after curl|bash)."""
    if sys.stdin.isatty():
        return
    try:
        sys.stdin = open("/dev/tty", encoding="utf-8")  # noqa: SIM115
    except OSError:
        print(
            "dj setup requires an interactive terminal.\n"
            "Run: dj setup",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    if not sys.stdin.isatty():
        print(
            "dj setup requires an interactive terminal.\n"
            "Run: dj setup",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _resolve_client_id(*, explicit: str | None, force: bool) -> str:
    if explicit and explicit.strip():
        cid = explicit.strip()
        config.set_spotify_client_id(cid)
        return cid

    existing = ""
    try:
        existing = config.resolve_spotify_client_id()
    except config.ConfigError:
        existing = str(config.load_app_config().get("spotify_client_id") or "").strip()

    if existing and not force:
        return existing

    cid = prompt(
        "Spotify Client ID",
        initial_value=existing,
        validator=lambda s: bool(str(s).strip()),
    )
    if cid is None:
        raise SystemExit("setup cancelled")
    cid = str(cid).strip()
    config.set_spotify_client_id(cid)
    return cid


def _pick_device(*, explicit: str | None) -> str | None:
    rows = spotify.list_devices()
    if explicit:
        match = next((d for d in rows if d.get("id") == explicit), None)
        if match is None:
            print(f"unknown device id: {explicit}", file=sys.stderr)
            raise SystemExit(1)
        spotify.save_preferred_device_id(explicit)
        spotify.transfer_playback(explicit, play=False)
        return explicit

    if not rows:
        for _ in range(5):
            if not confirm(
                "No devices found. Open Spotify on a speaker/phone, then retry?",
                default_is_yes=True,
            ):
                return None
            rows = spotify.list_devices()
            if rows:
                break
        if not rows:
            console.print("Still no devices; skipping device preference.")
            return None

    preferred = spotify.load_preferred_device_id()
    usable = [d for d in rows if d.get("id")]
    if not usable:
        return None

    labels = [device_label(d) for d in usable]
    cursor_index = 0
    if preferred:
        for i, d in enumerate(usable):
            if str(d["id"]) == preferred:
                cursor_index = i
                break

    console.print("Preferred playback device:")
    choice = select(labels, cursor_index=cursor_index, cursor="❯", cursor_style="cyan")
    if choice is None:
        return None
    selected = str(usable[labels.index(choice)]["id"])
    spotify.save_preferred_device_id(selected)
    spotify.transfer_playback(selected, play=False)
    return selected


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
            console.print("Spotify: keeping existing session.")
            return

    if not confirm(
        "Open your browser to authorize Spotify? (required)",
        default_is_yes=True,
    ):
        print("setup cancelled: Spotify login is required", file=sys.stderr)
        raise SystemExit(1)

    console.print("Spotify login…")
    spotify.ensure_session()
    console.print("Logged in.")


def _install_model() -> dict[str, Any]:
    if not confirm(
        "Download and load the MuQ embedding model?\n"
        "  Required for Claude DJ (~2.7 GB disk on first run; uses RAM)",
        default_is_yes=True,
    ):
        print("setup cancelled: embedding model is required", file=sys.stderr)
        raise SystemExit(1)

    spinner = Spinner(DOTS, "Loading MuQ embedding model…")
    spinner.start()
    try:
        from claude_dj.embeddings import ensure_model_loaded

        device = ensure_model_loaded()
    except Exception as exc:
        spinner.stop()
        print(f"embedding model failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    spinner.stop()
    console.print(f"Embedding model ready on {device}.")
    return {"ok": True, "action": "loaded", "device": device}


def run(
    *,
    client_id: str | None = None,
    device_id: str | None = None,
    force: bool = False,
    skip_claude: bool = False,
    skip_device: bool = False,
) -> dict[str, Any]:
    """Run interactive setup. Requires a TTY. MuQ model is mandatory."""
    _bind_tty()

    console.print("Claude DJ setup")
    console.print("---------------")

    try:
        cid = _resolve_client_id(explicit=client_id, force=force)
        masked = f"{cid[:4]}…{cid[-4:]}" if len(cid) > 8 else cid
        console.print(f"Client ID: {masked}")

        _spotify_login()

        chosen_device: str | None = None
        if not skip_device:
            console.print("Playback device…")
            chosen_device = _pick_device(explicit=device_id)
            if chosen_device:
                console.print(f"Device: {chosen_device}")
            else:
                console.print("Device: (none preferred)")

        statusline_out: dict[str, Any] | None = None
        skill_out: dict[str, Any] | None = None
        if not skip_claude:
            from claude_dj.integrate import statusline as statusline_mod

            console.print("Claude Code statusline…")
            statusline_out = statusline_mod.ensure_installed()
            console.print(f"  statusline: {statusline_out.get('action', statusline_out)}")
            console.print("Claude Code /dj skill…")
            skill_out = claude_code.install_skill()
            console.print(f"  skill: {skill_out.get('action', skill_out)}")

        model_out = _install_model()
    except KeyboardInterrupt:
        print(file=sys.stderr)
        raise SystemExit("setup cancelled") from None

    console.print()
    console.print("Done. Next: dj play")
    return {
        "ok": True,
        "spotify_client_id": cid,
        "device_id": chosen_device,
        "statusline": statusline_out,
        "skill": skill_out,
        "model": model_out,
    }
