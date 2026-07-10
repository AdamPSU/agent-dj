"""CLI entrypoint used by /dj commands.

This module parses user commands and talks to the local daemon.
"""

from pathlib import Path
from typing import TextIO
import argparse
import http.client
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

from claude_dj.adapters.spotify import SpotifyAuthError, SpotifyDevice, fetch_available_devices_with_token, perform_spotify_login
from claude_dj.config import (
    ensure_app_dir,
    get_runtime_file,
    get_spotify_config,
    get_spotify_device_file,
    get_spotify_token_file,
)
from claude_dj.devices import DevicePreference, load_device_preference, save_device_preference
from claude_dj.models import RuntimeInfo


STARTUP_TIMEOUT_SECONDS = 2.0


def main() -> int:
    """Run the Claude DJ CLI."""
    return run(sys.argv[1:])


def run(args: list[str], stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr) -> int:
    """Run a Claude DJ CLI command."""
    parser = argparse.ArgumentParser(prog="claude-dj")
    parser.add_argument("command", choices=["start", "sync", "status", "quit", "spotify-login", "devices", "device"])
    parser.add_argument("device_number", nargs="?")
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
    if namespace.command == "devices":
        return devices(stdout=stdout)
    if namespace.command == "device":
        return device(namespace.device_number, stdout=stdout)
    return 2


def start(stdout: TextIO, stderr: TextIO) -> int:
    """Start or attach to the local Claude DJ daemon."""
    runtime_info = ensure_daemon_running()

    try:
        response = post_json(
            runtime_info,
            "/session/start",
            {"session_id": "local-cli"},
        )
    except (OSError, TimeoutError, urllib.error.URLError, http.client.RemoteDisconnected):
        spawn_daemon()
        runtime_info = wait_for_daemon()
        response = post_json(
            runtime_info,
            "/session/start",
            {"session_id": "local-cli"},
        )
    stdout.write(f"{response['message']}\n")
    stdout.write("Storing your songs on device.\n")
    return 0


def sync(stdout: TextIO, stderr: TextIO) -> int:
    """Start or join local song storage in the daemon."""
    runtime_info = ensure_daemon_running()

    response = post_json(runtime_info, "/sync/start", {})
    stdout.write(f"{response['message']}\n")
    return 0


def status(stdout: TextIO) -> int:
    """Print local Claude DJ daemon status."""
    runtime_info = load_runtime_info()
    if runtime_info is None or not is_daemon_running(runtime_info):
        stdout.write("Claude DJ daemon is not running.\n")
        return 1

    response = get_json(runtime_info, "/status")
    response_host = response.get("host")
    response_port = response.get("port")
    host = response_host if isinstance(response_host, str) else runtime_info.host
    port = response_port if isinstance(response_port, int) else runtime_info.port
    stdout.write(f"Claude DJ daemon is running on {host}:{port}.\n")
    write_status_details(response, stdout)
    return 0


def write_status_details(response: dict[str, object], stdout: TextIO) -> None:
    """Print catalog and sync details returned by the daemon status endpoint."""
    sync = _dict_value(response, "sync")
    catalog = _dict_value(response, "catalog")
    indexing = _dict_value(response, "indexing")
    if not sync and not catalog and not indexing:
        return

    stdout.write("\n")
    if sync:
        stdout.write(f"Sync: {_display(sync.get('status'))}\n")
        error = sync.get("error")
        if isinstance(error, str) and error:
            stdout.write(f"Error: {error}\n")
    if indexing:
        write_spotify_indexing_error(indexing, stdout)
    if catalog:
        write_catalog_status(catalog, indexing, stdout)
    if indexing:
        write_last_run_status(indexing, stdout)


def write_catalog_status(catalog: dict[str, object], indexing: dict[str, object], stdout: TextIO) -> None:
    """Print catalog counts from daemon status."""
    stdout.write("Catalog:\n")
    stdout.write(f"  Playlists: {_int_value(catalog, 'source_count')}\n")
    stdout.write(f"  Tracks: {_int_value(catalog, 'track_count')}\n")
    stdout.write(
        "  Previews: "
        f"{_int_value(catalog, 'preview_match_count')} matched, "
        f"{_int_value(catalog, 'preview_pending_count')} pending\n"
    )
    stdout.write(
        "  Embeddings: "
        f"{_int_value(catalog, 'embedding_count')} ready, "
        f"{_int_value(catalog, 'embedding_pending_count')} pending\n"
    )
    embeddings = _dict_value(indexing, "embeddings")
    model = embeddings.get("model")
    dimensions = embeddings.get("dimensions")
    if isinstance(model, str) and isinstance(dimensions, int):
        stdout.write(f"  Model: {model}, {dimensions} dimensions\n")


def write_spotify_indexing_error(indexing: dict[str, object], stdout: TextIO) -> None:
    """Print Spotify indexing failures reported by background sync."""
    spotify = _dict_value(indexing, "spotify")
    error_code = spotify.get("error_code")
    if error_code not in {"spotify_auth_required", "spotify_access_denied"}:
        return
    message = spotify.get("message")
    if isinstance(message, str) and message:
        stdout.write(f"{message}\n")
    if error_code == "spotify_auth_required":
        stdout.write("Run: /dj spotify-login\n")


def write_last_run_status(indexing: dict[str, object], stdout: TextIO) -> None:
    """Print the last sync pipeline summaries if any phase ran."""
    spotify = _dict_value(indexing, "spotify")
    previews = _dict_value(indexing, "previews")
    embeddings = _dict_value(indexing, "embeddings")
    if not any(phase.get("ran") is True for phase in (spotify, previews, embeddings)):
        return

    stdout.write("\n")
    stdout.write("Last run:\n")
    if spotify.get("ran") is True:
        stdout.write(
            "  Spotify: indexed "
            f"{_int_value(spotify, 'playlist_count')} playlists, "
            f"{_int_value(spotify, 'track_count')} tracks, "
            f"skipped {_int_value(spotify, 'skipped_track_count')}\n"
        )
    if previews.get("ran") is True:
        stdout.write(
            "  Previews: "
            f"matched {_int_value(previews, 'matched_count')}, "
            f"failed {_int_value(previews, 'failed_count')}\n"
        )
    if embeddings.get("ran") is True:
        stdout.write(
            "  Embeddings: "
            f"embedded {_int_value(embeddings, 'embedded_count')}, "
            f"failed {_int_value(embeddings, 'failed_count')}\n"
        )


def _dict_value(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _int_value(data: dict[str, object], key: str) -> int:
    value = data.get(key)
    return value if isinstance(value, int) else 0


def _display(value: object) -> str:
    return value if isinstance(value, str) and value else "unknown"


def quit_daemon(stdout: TextIO) -> int:
    """Ask the local daemon to shut down."""
    runtime_info = load_runtime_info()
    if runtime_info is None or not is_daemon_running(runtime_info):
        stdout.write("Claude DJ daemon is not running.\n")
        return 0

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


def devices(stdout: TextIO) -> int:
    """List Spotify Connect devices visible to the current account."""
    try:
        available_devices = fetch_available_devices_with_token(token_file=get_spotify_token_file())
    except SpotifyAuthError as exc:
        stdout.write(f"{exc}\n")
        return 1

    preference = load_device_preference(get_spotify_device_file())
    if not available_devices:
        stdout.write("No Spotify devices found. Open Spotify on a device, then run /dj devices again.\n")
        return 1

    stdout.write("Spotify devices:\n")
    for index, spotify_device in enumerate(available_devices, start=1):
        stdout.write(_spotify_device_line(index, spotify_device, preference))
    return 0


def device(device_number: str | None, stdout: TextIO) -> int:
    """Persist a preferred Spotify Connect device by list number."""
    try:
        selected_number = int(device_number or "")
    except ValueError:
        stdout.write("Choose a device from /dj devices.\n")
        return 1

    try:
        available_devices = fetch_available_devices_with_token(token_file=get_spotify_token_file())
    except SpotifyAuthError as exc:
        stdout.write(f"{exc}\n")
        return 1

    if selected_number < 1 or selected_number > len(available_devices):
        stdout.write("Choose a device from /dj devices.\n")
        return 1

    selected_device = available_devices[selected_number - 1]
    if selected_device.is_restricted:
        stdout.write("Choose an unrestricted device from /dj devices.\n")
        return 1

    save_device_preference(get_spotify_device_file(), selected_device)
    stdout.write(f"Claude DJ playback device set to {selected_device.name}.\n")
    return 0


def _spotify_device_line(index: int, spotify_device: SpotifyDevice, preference: DevicePreference | None) -> str:
    status = _spotify_device_statuses(spotify_device, preference)
    suffix = f" {' '.join(status)}" if status else ""
    return f"  {index}. {spotify_device.name} [{spotify_device.type}]{suffix}\n"


def _spotify_device_statuses(spotify_device: SpotifyDevice, preference: DevicePreference | None) -> list[str]:
    status: list[str] = []
    if spotify_device.is_active:
        status.append("active")
    elif not spotify_device.is_restricted:
        status.append("available")
    if spotify_device.is_restricted:
        status.append("restricted")
    if _device_matches_preference(spotify_device, preference):
        status.append("selected")
    return status


def _device_matches_preference(spotify_device: SpotifyDevice, preference: DevicePreference | None) -> bool:
    if preference is None:
        return False
    return spotify_device.id == preference.id or (spotify_device.name == preference.name and spotify_device.type == preference.type)


def load_runtime_info(runtime_file: Path | None = None) -> RuntimeInfo | None:
    """Read daemon location from the runtime file."""
    path = runtime_file or get_runtime_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return RuntimeInfo.from_json(data)


def ensure_daemon_running() -> RuntimeInfo:
    """Return a live daemon location, spawning the daemon when needed."""
    runtime_info = load_runtime_info()
    if runtime_info is not None and is_daemon_running(runtime_info):
        return runtime_info
    spawn_daemon()
    return wait_for_daemon()


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
