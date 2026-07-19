"""Interactive (questionary) and non-interactive setup for Claude DJ."""

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


def _resolve_client_id(
    *,
    explicit: str | None,
    force: bool,
    interactive: bool,
) -> str:
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

    if not interactive:
        print(
            "Spotify client ID required; pass --client-id or run setup in a TTY",
            file=sys.stderr,
        )
        raise SystemExit(2)

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


def _pick_device(
    *,
    explicit: str | None,
    interactive: bool,
) -> str | None:
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
        if not interactive:
            _print("No Spotify devices found; open Spotify on a device and re-run setup.")
            return None
        import questionary

        for _ in range(5):
            again = questionary.confirm(
                "No devices found. Open Spotify on a speaker/phone, then retry?",
                default=True,
            ).ask()
            if again is None:
                raise SystemExit("setup cancelled")
            if not again:
                return None
            rows = spotify.list_devices()
            if rows:
                break
        if not rows:
            _print("Still no devices; skipping device preference.")
            return None

    preferred = spotify.load_preferred_device_id()
    if not interactive:
        # Non-interactive without --device-id: keep existing preferred if still listed
        if preferred and any(d.get("id") == preferred for d in rows):
            return preferred
        if len(rows) == 1:
            did = str(rows[0]["id"])
            spotify.save_preferred_device_id(did)
            spotify.transfer_playback(did, play=False)
            return did
        _print("Multiple devices; pass --device-id to select one.")
        return preferred

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


def run(
    *,
    client_id: str | None = None,
    device_id: str | None = None,
    yes: bool = False,
    force: bool = False,
    skip_claude: bool = False,
    skip_device: bool = False,
) -> dict[str, Any]:
    """Run setup. Interactive when stdin is a TTY and not --yes."""
    interactive = (not yes) and sys.stdin.isatty()

    _print("Claude DJ setup")
    _print("---------------")

    cid = _resolve_client_id(
        explicit=client_id,
        force=force,
        interactive=interactive,
    )
    _print(f"Client ID: {cid[:4]}…{cid[-4:]}" if len(cid) > 8 else f"Client ID: {cid}")

    _print("Spotify login…")
    spotify.ensure_session()
    _print("Logged in.")

    chosen_device: str | None = None
    if not skip_device:
        _print("Playback device…")
        chosen_device = _pick_device(explicit=device_id, interactive=interactive)
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

    _print()
    _print("Done. Next: claude-dj play")
    return {
        "ok": True,
        "spotify_client_id": cid,
        "device_id": chosen_device,
        "statusline": statusline_out,
        "skill": skill_out,
    }


def uninstall(*, wipe: bool = False, yes: bool = False) -> dict[str, Any]:
    """Remove Claude Code integrations; optionally wipe ~/.claude-dj."""
    from claude_dj.integrate import statusline as statusline_mod

    interactive = (not yes) and sys.stdin.isatty()
    if wipe and interactive:
        import questionary

        ok = questionary.confirm(
            f"Delete all Claude DJ data under {config.APP_DIR}?",
            default=False,
        ).ask()
        if not ok:
            return {"ok": True, "action": "cancelled"}
    elif wipe and not yes:
        raise SystemExit("refusing wipe without --yes in non-interactive mode")

    sl = statusline_mod.uninstall()
    skill = claude_code.uninstall_skill()
    wiped = False
    if wipe and config.APP_DIR.exists():
        import shutil

        shutil.rmtree(config.APP_DIR)
        wiped = True
    return {
        "ok": True,
        "statusline": sl,
        "skill": skill,
        "wiped": wiped,
    }
