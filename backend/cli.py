import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

from backend.config import BASE_URL, SPOTIFY_TOKEN_PATH


def request(method: str, path: str) -> dict:
    """Send one control request to the local daemon and return its JSON reply."""
    data = b"" if method == "POST" else None
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, method=method)
    with urllib.request.urlopen(req, timeout=2) as resp:
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
    subprocess.Popen(
        [sys.executable, "-m", "backend.cli", "__daemon__"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        if reachable():
            return
        time.sleep(0.1)
    raise SystemExit("daemon failed to start")


def ensure_spotify_login() -> None:
    """If the user has never logged into Spotify here, run the browser login first."""
    if SPOTIFY_TOKEN_PATH.exists():
        return
    from backend.adapters.spotify import login

    login()


def main(argv: list[str] | None = None) -> None:
    """Run a user command, or the hidden background-server mode used by start."""
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "__daemon__":
        from backend.daemon import main as daemon_main

        daemon_main()
        return

    parser = argparse.ArgumentParser(prog="claude-dj")
    parser.add_argument(
        "command",
        choices=["start", "status", "sync", "quit", "spotify-login"],
    )
    args = parser.parse_args(argv)

    if args.command == "spotify-login":
        from backend.adapters.spotify import login

        print(json.dumps(login()))
        return

    try:
        if args.command == "start":
            ensure_spotify_login()
            ensure_daemon()
            body = request("POST", "/start")
        elif args.command == "status":
            body = request("GET", "/status")
        elif args.command == "sync":
            body = request("POST", "/sync")
        else:
            body = request("POST", "/quit")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc

    print(json.dumps(body))


if __name__ == "__main__":
    main()
