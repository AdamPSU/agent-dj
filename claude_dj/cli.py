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
    """Ensure Spotify works before play: refresh tokens if needed, else browser login."""
    from claude_dj.adapters.spotify import ensure_session

    ensure_session()


def _cmd_setup(argv: list[str]) -> None:
    from claude_dj.integrate import setup as setup_wizard

    parser = argparse.ArgumentParser(prog="claude-dj setup")
    parser.add_argument("--client-id", default=None, help="Spotify app client ID")
    parser.add_argument("--device-id", default=None, help="Preferred Connect device id")
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Non-interactive; require flags for missing values",
    )
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
    out = setup_wizard.run(
        client_id=args.client_id,
        device_id=args.device_id,
        yes=args.yes,
        force=args.force,
        skip_claude=args.skip_claude,
        skip_device=args.skip_device,
    )
    print(json.dumps(out))


def _cmd_uninstall(argv: list[str]) -> None:
    from claude_dj.integrate import setup as setup_wizard

    parser = argparse.ArgumentParser(prog="claude-dj uninstall")
    parser.add_argument(
        "--wipe",
        action="store_true",
        help=f"Also delete {APP_DIR} (tokens, catalog, config)",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation for --wipe",
    )
    args = parser.parse_args(argv)
    out = setup_wizard.uninstall(wipe=args.wipe, yes=args.yes)
    print(json.dumps(out))


def _cmd_statusline(argv: list[str]) -> None:
    from claude_dj.integrate import statusline as statusline_mod

    sub = argv[0] if argv else None
    if sub == "uninstall":
        print(json.dumps(statusline_mod.uninstall()))
        return
    if sub not in (None, "run"):
        print(f"unknown statusline subcommand: {sub}", file=sys.stderr)
        raise SystemExit(2)
    out = statusline_mod.run()
    if out:
        sys.stdout.write(out if out.endswith("\n") else out + "\n")


def main(argv: list[str] | None = None) -> None:
    """Run a user command, or the hidden background-server mode used by play."""
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "__daemon__":
        from claude_dj.daemon.server import main as daemon_main

        daemon_main()
        return

    if not argv:
        print(
            "usage: claude-dj <setup|play|status|sync|device|quit|statusline|uninstall>",
            file=sys.stderr,
        )
        raise SystemExit(2)

    cmd, rest = argv[0], argv[1:]

    if cmd == "setup":
        _cmd_setup(rest)
        return
    if cmd == "uninstall":
        _cmd_uninstall(rest)
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
        print(json.dumps(body))
        return

    if cmd not in ("play", "status", "sync", "quit"):
        print(f"unknown command: {cmd}", file=sys.stderr)
        raise SystemExit(2)

    try:
        if cmd == "play":
            from claude_dj.integrate import statusline as statusline_mod

            statusline_mod.ensure_installed()
            ensure_spotify_login()
            ensure_daemon()
            body = request("POST", "/play")
        elif cmd == "status":
            body = request("GET", "/status")
        elif cmd == "sync":
            body = request("POST", "/sync")
        else:
            body = request("POST", "/quit")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc

    print(json.dumps(body))


if __name__ == "__main__":
    main()
