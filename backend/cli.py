import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from backend.config import APP_DIR, BASE_URL

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
        [sys.executable, "-m", "backend.cli", "__daemon__"],
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
    from backend.adapters.spotify import ensure_session

    ensure_session()


def main(argv: list[str] | None = None) -> None:
    """Run a user command, or the hidden background-server mode used by play."""
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "__daemon__":
        from backend.daemon import main as daemon_main

        daemon_main()
        return

    parser = argparse.ArgumentParser(prog="claude-dj")
    parser.add_argument(
        "command",
        choices=["play", "status", "sync", "device", "quit"],
    )
    parser.add_argument(
        "device_id",
        nargs="?",
        default=None,
        help="with `device`: Spotify device id to prefer (omit to list)",
    )
    args = parser.parse_args(argv)

    try:
        if args.command == "play":
            ensure_spotify_login()
            ensure_daemon()
            body = request("POST", "/play")
        elif args.command == "status":
            body = request("GET", "/status")
        elif args.command == "sync":
            body = request("POST", "/sync")
        elif args.command == "device":
            ensure_spotify_login()
            ensure_daemon()
            if args.device_id:
                body = request("POST", f"/devices/{args.device_id}")
            else:
                body = request("GET", "/devices")
        else:
            body = request("POST", "/quit")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc

    print(json.dumps(body))


if __name__ == "__main__":
    main()
