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


STARTUP_TIMEOUT_SECONDS = 2.0
SESSION_START_TIMEOUT_SECONDS = 600


def main() -> int:
    """Run the Claude DJ CLI."""
    return run(sys.argv[1:])


def run(args: list[str], stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr) -> int:
    """Run a Claude DJ CLI command."""
    parser = argparse.ArgumentParser(prog="claude-dj")
    parser.add_argument("command", choices=["start", "sync", "status", "quit", "spotify-login"])
    namespace = parser.parse_args(args)

    if namespace.command == "start":
        return start(stdout=stdout, stderr=stderr)
    if namespace.command == "sync":
        return sync(stdout=stdout, stderr=stderr)
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

    response = post_json(
        runtime_info,
        "/session/start",
        {"session_id": "local-cli"},
        timeout_seconds=SESSION_START_TIMEOUT_SECONDS,
    )
    stdout.write(f"{response['message']}\n")
    write_start_details(response, stdout)
    return 0


def sync(stdout: TextIO, stderr: TextIO) -> int:
    """Start or join local song storage in the daemon."""
    runtime_info = load_runtime_info()
    if runtime_info is None or not is_daemon_running(runtime_info):
        spawn_daemon()
        runtime_info = wait_for_daemon()

    response = post_json(runtime_info, "/sync/start", {})
    stdout.write(f"{response['message']}\n")
    return 0


def write_start_details(response: dict[str, object], stdout: TextIO) -> None:
    """Print startup catalog/indexing details returned by the daemon."""
    spotify_indexing = _spotify_indexing(response)
    error_code = spotify_indexing.get("error_code")
    if error_code in {"spotify_auth_required", "spotify_access_denied"}:
        message = spotify_indexing.get("message")
        if isinstance(message, str):
            stdout.write(f"{message}\n")
        if error_code == "spotify_auth_required":
            stdout.write("Run: /dj spotify-login\n")
        return

    stdout.write("Storing your songs on device.\n")
    return


def _spotify_indexing(response: dict[str, object]) -> dict[str, object]:
    return _indexing_result(response, "spotify")


def _indexing_result(response: dict[str, object], key: str) -> dict[str, object]:
    indexing = response.get("indexing")
    if not isinstance(indexing, dict):
        return {}
    result = indexing.get(key)
    return result if isinstance(result, dict) else {}


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


def post_json(
    runtime_info: RuntimeInfo,
    path: str,
    body: dict[str, object],
    timeout_seconds: int = 2,
) -> dict[str, object]:
    """Send a JSON POST request to the local daemon."""
    request = urllib.request.Request(
        f"{runtime_info.base_url}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
