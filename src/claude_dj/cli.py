"""CLI entrypoint used by /dj commands.

This module will parse user commands and talk to the local daemon.
"""

from pathlib import Path
from typing import TextIO
import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

from claude_dj.adapters.spotify import perform_spotify_login
from claude_dj.config import ensure_app_dir, get_runtime_file, get_spotify_config, get_spotify_token_file
from claude_dj.models import RuntimeInfo


STARTUP_TIMEOUT_SECONDS = 5.0


def main() -> int:
    """Run the Claude DJ CLI."""
    return run(sys.argv[1:])


def run(args: list[str], stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr) -> int:
    """Run a Claude DJ CLI command."""
    parser = argparse.ArgumentParser(prog="claude-dj")
    parser.add_argument("command", choices=["start", "status", "quit", "spotify-login"])
    namespace = parser.parse_args(args)

    if namespace.command == "start":
        return start(stdout=stdout, stderr=stderr)
    if namespace.command == "status":
        return status(stdout=stdout)
    if namespace.command == "quit":
        return quit_daemon(stdout=stdout)
    if namespace.command == "spotify-login":
        return spotify_login(stdout=stdout)
    return 2


def start(stdout: TextIO, stderr: TextIO) -> int:
    """Start or attach to the local Claude DJ daemon."""
    runtime_info = load_runtime_info()
    if runtime_info is None or not is_daemon_running(runtime_info):
        spawn_daemon()
        runtime_info = wait_for_daemon()

    response = post_json(runtime_info, "/session/start", {"session_id": "local-cli"})
    stdout.write(f"{response['message']}\n")
    catalog = response.get("catalog", {})
    if isinstance(catalog, dict) and catalog.get("needs_onboarding") is True:
        stdout.write("Indexing all Spotify playlists is needed before DJ mode is ready.\n")
    return 0


def status(stdout: TextIO) -> int:
    """Print local Claude DJ daemon status."""
    runtime_info = load_runtime_info()
    if runtime_info is None or not is_daemon_running(runtime_info):
        stdout.write("Claude DJ daemon is not running.\n")
        return 1

    stdout.write(f"Claude DJ daemon is running on {runtime_info.host}:{runtime_info.port}.\n")
    return 0


def quit_daemon(stdout: TextIO) -> int:
    """Ask the local daemon to shut down."""
    runtime_info = load_runtime_info()
    if runtime_info is None or not is_daemon_running(runtime_info):
        stdout.write("Claude DJ daemon is not running.\n")
        return 1

    response = post_json(runtime_info, "/daemon/quit", {})
    stdout.write(f"{response['message']}\n")
    return 0


def spotify_login(stdout: TextIO) -> int:
    """Run Spotify browser login and save the local token cache."""
    perform_spotify_login(
        config=get_spotify_config(),
        token_file=get_spotify_token_file(),
    )
    stdout.write("Spotify login complete.\n")
    return 0


def load_runtime_info(runtime_file: Path | None = None) -> RuntimeInfo | None:
    """Read daemon location from the runtime file."""
    path = runtime_file or get_runtime_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return RuntimeInfo.from_json(data)


def is_daemon_running(runtime_info: RuntimeInfo) -> bool:
    """Return whether the runtime file points to a live daemon."""
    try:
        get_json(runtime_info, "/status")
    except (OSError, urllib.error.URLError, TimeoutError):
        return False
    return True


def spawn_daemon() -> None:
    """Start the local daemon process in the background."""
    ensure_app_dir()
    subprocess.Popen(
        [sys.executable, "-m", "claude_dj.daemon"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def wait_for_daemon(timeout_seconds: float = STARTUP_TIMEOUT_SECONDS) -> RuntimeInfo:
    """Wait for a newly spawned daemon to write its runtime file and respond."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        runtime_info = load_runtime_info()
        if runtime_info is not None and is_daemon_running(runtime_info):
            return runtime_info
        time.sleep(0.05)
    raise RuntimeError("Claude DJ daemon did not start in time.")


def get_json(runtime_info: RuntimeInfo, path: str) -> dict[str, object]:
    """Send a GET request to the local daemon."""
    request = urllib.request.Request(f"{runtime_info.base_url}{path}", method="GET")
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(runtime_info: RuntimeInfo, path: str, body: dict[str, object]) -> dict[str, object]:
    """Send a JSON POST request to the local daemon."""
    request = urllib.request.Request(
        f"{runtime_info.base_url}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
