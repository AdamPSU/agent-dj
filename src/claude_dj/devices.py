"""Spotify playback device preference and selection policy."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
import json

from claude_dj.adapters.spotify import (
    SpotifyDevice,
    SpotifyNoActiveDeviceError,
    fetch_available_devices_with_token,
    start_playback_with_token,
)


@dataclass(frozen=True)
class DevicePreference:
    """Persisted preferred Spotify Connect device."""

    id: str
    name: str
    type: str


@dataclass(frozen=True)
class PlaybackDeviceResult:
    """Device chosen after active-device playback failed."""

    device: SpotifyDevice | None
    used_fallback: bool
    preferred_unavailable: bool


DeviceFetcher = Callable[..., list[SpotifyDevice]]
PlaybackStarter = Callable[..., None]


def load_device_preference(device_file: Path) -> DevicePreference | None:
    """Load the preferred Spotify device if one has been saved."""
    try:
        data = json.loads(device_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    device_id = data.get("id")
    name = data.get("name")
    device_type = data.get("type")
    if not all(isinstance(value, str) and value for value in (device_id, name, device_type)):
        return None
    return DevicePreference(id=str(device_id), name=str(name), type=str(device_type))


def save_device_preference(device_file: Path, device: SpotifyDevice) -> None:
    """Persist the selected Spotify device for future playback starts."""
    device_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    device_file.write_text(
        json.dumps({"id": device.id, "name": device.name, "type": device.type}, indent=2),
        encoding="utf-8",
    )
    device_file.chmod(0o600)


def choose_playback_device(
    devices: Sequence[SpotifyDevice],
    preference: DevicePreference | None,
) -> tuple[SpotifyDevice | None, bool]:
    """Choose a saved usable device, requiring explicit user choice otherwise."""
    usable = [device for device in devices if not device.is_restricted]
    if preference is None or not usable:
        return None, preference is not None

    for device in usable:
        if device.id == preference.id:
            return device, False
    for device in usable:
        if device.name == preference.name and device.type == preference.type:
            return device, False

    return None, True


def start_playback_with_device_policy(
    *,
    token_file: Path,
    device_file: Path,
    spotify_uris: Sequence[str],
    start_playback: PlaybackStarter = start_playback_with_token,
    fetch_devices: DeviceFetcher = fetch_available_devices_with_token,
    **kwargs,
) -> PlaybackDeviceResult | None:
    """Start playback, choosing an available device when Spotify has no active device."""
    try:
        start_playback(token_file=token_file, spotify_uris=spotify_uris, **kwargs)
        return None
    except SpotifyNoActiveDeviceError:
        devices = fetch_devices(token_file=token_file, **kwargs)
        preference = load_device_preference(device_file)
        selected, preferred_unavailable = choose_playback_device(
            devices,
            preference,
        )
        if selected is None:
            raise SpotifyNoActiveDeviceError(_choose_device_message(devices))
        start_playback(
            token_file=token_file,
            spotify_uris=spotify_uris,
            device_id=selected.id,
            **kwargs,
        )
        return PlaybackDeviceResult(
            device=selected,
            used_fallback=True,
            preferred_unavailable=preferred_unavailable,
        )


def _choose_device_message(devices: Sequence[SpotifyDevice]) -> str:
    if not devices:
        return "No active Spotify device found. Open Spotify on a device, then run /dj start again."

    lines = ["No active Spotify device found.", "Choose a playback device:"]
    for index, device in enumerate(devices, start=1):
        suffix = " restricted" if device.is_restricted else ""
        lines.append(f"  {index}. {device.name} [{device.type}]{suffix}")
    lines.extend(["Run: /dj device <number>", "Then run: /dj start"])
    return "\n".join(lines)
