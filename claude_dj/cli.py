import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from claude_dj.config import APP_DIR, BASE_URL

DAEMON_WAIT_ATTEMPTS = 100  # 100 * 0.1s = 10s
DAEMON_LOG = APP_DIR / "daemon.log"

HELP_TEXT = """\
dj — local Spotify coding companion

Commands:
  setup                 Interactive setup (Spotify + MuQ + statusline)
  jam                   Start/resume recommender; enables statusline
  kill                  Stop daemon (jam + bar process). Spotify keeps playing
  statusline            Toggle Claude Code status bar on/off
  sync                  Kick catalog sync
  device [id]           List Connect devices, or prefer one
  help                  Show this help

Examples:
  dj setup
  dj jam
  dj statusline
  dj kill
"""


def request(method: str, path: str, body: dict | None = None) -> dict:
    """Send one control request to the local daemon and return its JSON reply."""
    data = None
    if method == "POST":
        data = b"" if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def reachable() -> bool:
    """True when the background daemon is already answering requests."""
    try:
        request("GET", "/status")
        return True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False


def ensure_daemon() -> None:
    """Start the background daemon if it is not already running, then wait until it responds."""
    if reachable():
        return

    APP_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = open(DAEMON_LOG, "ab", buffering=0)
    proc = subprocess.Popen(
        [sys.executable, "-m", "claude_dj.cli", "__daemon__"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    log_handle.close()

    for _ in range(DAEMON_WAIT_ATTEMPTS):
        if reachable():
            return
        if proc.poll() is not None:
            tail = _daemon_log_tail()
            raise SystemExit(
                "daemon exited before becoming ready "
                f"(exit={proc.returncode}). log: {DAEMON_LOG}\n{tail}"
            )
        time.sleep(0.1)

    tail = _daemon_log_tail()
    raise SystemExit(
        f"daemon failed to start within {DAEMON_WAIT_ATTEMPTS * 0.1:.0f}s. "
        f"log: {DAEMON_LOG}\n{tail}"
    )


def _daemon_log_tail(max_bytes: int = 2000) -> str:
    path = Path(DAEMON_LOG)
    if not path.exists():
        return "(no daemon log)"
    data = path.read_bytes()
    if not data:
        return "(daemon log empty)"
    text = data[-max_bytes:].decode(errors="replace").strip()
    return text or "(daemon log empty)"


def ensure_spotify_login() -> None:
    """Ensure Spotify works before jam: refresh tokens if needed, else browser login."""
    from claude_dj.adapters.spotify import ensure_session

    ensure_session()


def _cmd_setup(argv: list[str]) -> None:
    from claude_dj.integrate import setup as setup_wizard

    parser = argparse.ArgumentParser(prog="dj setup")
    parser.add_argument("--client-id", default=None, help="Spotify app client ID")
    parser.add_argument("--device-id", default=None, help="Preferred Connect device id")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-prompt even when already configured",
    )
    parser.add_argument(
        "--skip-claude",
        action="store_true",
        help="Skip statusline and /dj skill install",
    )
    parser.add_argument(
        "--skip-device",
        action="store_true",
        help="Skip playback device selection",
    )
    args = parser.parse_args(argv)
    setup_wizard.run(
        client_id=args.client_id,
        device_id=args.device_id,
        force=args.force,
        skip_claude=args.skip_claude,
        skip_device=args.skip_device,
    )


def _cmd_statusline(argv: list[str]) -> None:
    """Toggle bar for users; `--render` is the Claude Code statusLine hook."""
    from claude_dj.integrate import statusline as statusline_mod

    if argv == ["--render"] or argv == ["render"]:
        rendered = statusline_mod.run()
        if rendered:
            sys.stdout.write(rendered if rendered.endswith("\n") else rendered + "\n")
        return

    if argv:
        print(f"unknown statusline argument: {argv[0]}", file=sys.stderr)
        raise SystemExit(2)

    out = statusline_mod.toggle()
    _emit(out)


def _cmd_help() -> None:
    sys.stdout.write(HELP_TEXT)


def main(argv: list[str] | None = None) -> None:
    """Run a user command, or the hidden background-server mode used by jam."""
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "__daemon__":
        from claude_dj.daemon.server import main as daemon_main

        daemon_main()
        return

    if not argv or argv[0] in ("help", "-h", "--help"):
        _cmd_help()
        return

    cmd, rest = argv[0], argv[1:]

    if cmd == "setup":
        _cmd_setup(rest)
        return
    if cmd == "statusline":
        _cmd_statusline(rest)
        return

    if cmd == "device":
        device_id = rest[0] if rest else None
        try:
            ensure_spotify_login()
            ensure_daemon()
            if device_id:
                body = request("POST", f"/devices/{device_id}")
            else:
                body = request("GET", "/devices")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(exc, file=sys.stderr)
            raise SystemExit(1) from exc
        _emit(body)
        return

    if cmd == "jam":
        try:
            from claude_dj.integrate import statusline as statusline_mod

            statusline_mod.ensure_installed()
            ensure_spotify_login()
            ensure_daemon()
            body = request("POST", "/jam")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(exc, file=sys.stderr)
            raise SystemExit(1) from exc
        _emit(body)
        return

    if cmd == "sync":
        try:
            if not reachable():
                ensure_spotify_login()
                ensure_daemon()
            body = request("POST", "/sync")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(exc, file=sys.stderr)
            raise SystemExit(1) from exc
        _emit(body)
        return

    if cmd == "kill":
        try:
            if not reachable():
                print(json.dumps({"ok": True}))
                return
            body = request("POST", "/kill")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(exc, file=sys.stderr)
            raise SystemExit(1) from exc
        _emit(body)
        return

    print(f"unknown command: {cmd}", file=sys.stderr)
    _cmd_help()
    raise SystemExit(2)


def _emit(body: dict) -> None:
    """Print JSON reply; exit 1 when the daemon reports failure."""
    print(json.dumps(body))
    if body.get("ok") is False:
        err = body.get("error") or "failed"
        detail = body.get("detail")
        hint = body.get("hint")
        parts = [str(err)]
        if detail:
            parts.append(str(detail))
        if hint:
            parts.append(f"hint: {hint}")
        print("; ".join(parts), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
