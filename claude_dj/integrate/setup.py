"""Interactive setup wizard for Claude DJ (TTY required)."""

from __future__ import annotations

import sys
from typing import Any

from claude_dj import config
from claude_dj.adapters import spotify
from claude_dj.integrate import claude_code


def device_label(row: dict[str, Any]) -> str:
    """Human label for a Spotify Connect device row."""
    name = str(row.get("name") or "Unknown")
    kind = str(row.get("type") or "Device")
    base = f"{name} ({kind})"
    if row.get("is_active"):
        return f"{base} · active"
    return base


def _print(msg: str = "") -> None:
    print(msg)


def _confirm(message: str, *, default: bool = True) -> bool:
    """Ask yes/no. Cancel (Ctrl+C / Esc) aborts setup."""
    import questionary

    answer = questionary.confirm(message, default=default).ask()
    if answer is None:
        raise SystemExit("setup cancelled")
    return bool(answer)


def _require_tty() -> None:
    """Ensure stdin is a real TTY (reopen /dev/tty after curl|bash)."""
    if sys.stdin.isatty():
        return
    try:
        # Piped install leaves stdin as the script stream; use the console.
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

    import questionary

    while True:
        answer = questionary.text(
            "Spotify Client ID:",
            default=existing or "",
            validate=lambda t: True if (t or "").strip() else "Client ID is required",
        ).ask()
        if answer is None:
            raise SystemExit("setup cancelled")
        cid = answer.strip()
        if cid:
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
            again = _confirm(
                "No devices found. Open Spotify on a speaker/phone, then retry?",
                default=True,
            )
            if not again:
                return None
            rows = spotify.list_devices()
            if rows:
                break
        if not rows:
            _print("Still no devices; skipping device preference.")
            return None

    preferred = spotify.load_preferred_device_id()
    import questionary
    from questionary import Choice

    choices = [
        Choice(title=device_label(d), value=str(d["id"]))
        for d in rows
        if d.get("id")
    ]
    default = preferred if preferred and any(c.value == preferred for c in choices) else None
    selected = questionary.select(
        "Preferred playback device:",
        choices=choices,
        default=default,
    ).ask()
    if selected is None:
        raise SystemExit("setup cancelled")
    spotify.save_preferred_device_id(selected)
    spotify.transfer_playback(selected, play=False)
    return selected


def _spotify_login() -> None:
    """Confirm, then open browser OAuth if needed."""
    already = False
    try:
        already = spotify.session_is_valid()
    except Exception:
        already = False

    if already:
        if not _confirm(
            "Spotify is already logged in. Re-authenticate anyway?",
            default=False,
        ):
            _print("Spotify: keeping existing session.")
            return

    if not _confirm(
        "Open your browser to authorize Spotify? (required)",
        default=True,
    ):
        print("setup cancelled: Spotify login is required", file=sys.stderr)
        raise SystemExit(1)

    _print("Spotify login…")
    spotify.ensure_session()
    _print("Logged in.")


def _install_model() -> dict[str, Any]:
    """Confirm, then download/load MuQ. Required — no product without it."""
    if not _confirm(
        "Download and load the MuQ embedding model?\n"
        "  Required for Claude DJ (~2.7 GB disk on first run; uses RAM)",
        default=True,
    ):
        print(
            "setup cancelled: embedding model is required",
            file=sys.stderr,
        )
        raise SystemExit(1)

    _print("Loading MuQ embedding model (may download weights)…")
    try:
        from claude_dj.embeddings import ensure_model_loaded

        device = ensure_model_loaded()
    except Exception as exc:
        print(f"embedding model failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    _print(f"Embedding model ready on {device}.")
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
    _require_tty()

    _print("Claude DJ setup")
    _print("---------------")

    cid = _resolve_client_id(explicit=client_id, force=force)
    _print(f"Client ID: {cid[:4]}…{cid[-4:]}" if len(cid) > 8 else f"Client ID: {cid}")

    _spotify_login()

    chosen_device: str | None = None
    if not skip_device:
        _print("Playback device…")
        chosen_device = _pick_device(explicit=device_id)
        if chosen_device:
            _print(f"Device: {chosen_device}")
        else:
            _print("Device: (none preferred)")

    statusline_out: dict[str, Any] | None = None
    skill_out: dict[str, Any] | None = None
    if not skip_claude:
        from claude_dj.integrate import statusline as statusline_mod

        _print("Claude Code statusline…")
        statusline_out = statusline_mod.ensure_installed()
        _print(f"  statusline: {statusline_out.get('action', statusline_out)}")
        _print("Claude Code /dj skill…")
        skill_out = claude_code.install_skill()
        _print(f"  skill: {skill_out.get('action', skill_out)}")

    model_out = _install_model()

    _print()
    _print("Done. Next: dj play")
    return {
        "ok": True,
        "spotify_client_id": cid,
        "device_id": chosen_device,
        "statusline": statusline_out,
        "skill": skill_out,
        "model": model_out,
    }


