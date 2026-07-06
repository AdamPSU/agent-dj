"""Spotify playback device preference and selection policy tests."""

import pytest

from claude_dj.adapters.spotify import SpotifyDevice, SpotifyNoActiveDeviceError
from claude_dj.devices import (
    DevicePreference,
    PlaybackDeviceResult,
    choose_playback_device,
    load_device_preference,
    save_device_preference,
    start_playback_with_device_policy,
)


def test_device_preference_round_trip(tmp_path) -> None:
    device_file = tmp_path / "spotify-device.json"
    device = SpotifyDevice(
        id="device-1",
        name="MacBook",
        type="Computer",
        is_active=False,
        is_restricted=False,
    )

    save_device_preference(device_file, device)

    assert load_device_preference(device_file) == DevicePreference(
        id="device-1",
        name="MacBook",
        type="Computer",
    )


def test_choose_playback_device_prefers_saved_id_then_saved_name() -> None:
    preferred = DevicePreference(id="old-id", name="MacBook", type="Computer")
    devices = [
        SpotifyDevice(
            id="speaker-1",
            name="Kitchen Speaker",
            type="Speaker",
            is_active=False,
            is_restricted=False,
        ),
        SpotifyDevice(
            id="new-id",
            name="MacBook",
            type="Computer",
            is_active=False,
            is_restricted=False,
        ),
    ]

    selected, preferred_unavailable = choose_playback_device(devices, preferred)

    assert selected == devices[1]
    assert preferred_unavailable is False


def test_choose_playback_device_stops_when_preference_unavailable() -> None:
    preferred = DevicePreference(id="missing-id", name="Missing", type="Computer")
    devices = [
        SpotifyDevice(
            id="restricted-1",
            name="Restricted",
            type="Speaker",
            is_active=False,
            is_restricted=True,
        ),
        SpotifyDevice(
            id="speaker-1",
            name="Kitchen Speaker",
            type="Speaker",
            is_active=False,
            is_restricted=False,
        ),
    ]

    selected, preferred_unavailable = choose_playback_device(devices, preferred)

    assert selected is None
    assert preferred_unavailable is True


def test_choose_playback_device_stops_without_preference() -> None:
    devices = [
        SpotifyDevice(
            id="speaker-1",
            name="Kitchen Speaker",
            type="Speaker",
            is_active=False,
            is_restricted=False,
        )
    ]

    selected, preferred_unavailable = choose_playback_device(devices, None)

    assert selected is None
    assert preferred_unavailable is False


def test_start_playback_with_device_policy_retries_on_selected_device(tmp_path) -> None:
    token_file = tmp_path / "spotify-token.json"
    device_file = tmp_path / "spotify-device.json"
    playback_calls = []
    save_device_preference(
        device_file,
        SpotifyDevice(
            id="device-1",
            name="MacBook",
            type="Computer",
            is_active=False,
            is_restricted=False,
        ),
    )

    def fake_start_playback(token_file, spotify_uris, device_id=None, **kwargs):
        playback_calls.append((tuple(spotify_uris), device_id))
        if device_id is None:
            raise SpotifyNoActiveDeviceError("No active Spotify device found.")

    def fake_fetch_devices(**kwargs):
        return [
            SpotifyDevice(
                id="device-1",
                name="MacBook",
                type="Computer",
                is_active=False,
                is_restricted=False,
            )
        ]

    result = start_playback_with_device_policy(
        token_file=token_file,
        device_file=device_file,
        spotify_uris=("spotify:track:1",),
        start_playback=fake_start_playback,
        fetch_devices=fake_fetch_devices,
    )

    assert playback_calls == [
        (("spotify:track:1",), None),
        (("spotify:track:1",), "device-1"),
    ]
    assert result == PlaybackDeviceResult(
        device=SpotifyDevice(
            id="device-1",
            name="MacBook",
            type="Computer",
            is_active=False,
            is_restricted=False,
        ),
        used_fallback=True,
        preferred_unavailable=False,
    )


def test_start_playback_with_device_policy_asks_user_to_choose_without_preference(tmp_path) -> None:
    token_file = tmp_path / "spotify-token.json"
    device_file = tmp_path / "spotify-device.json"
    playback_calls = []

    def fake_start_playback(token_file, spotify_uris, device_id=None, **kwargs):
        playback_calls.append((tuple(spotify_uris), device_id))
        raise SpotifyNoActiveDeviceError("No active Spotify device found.")

    def fake_fetch_devices(**kwargs):
        return [
            SpotifyDevice(
                id="device-1",
                name="MacBook",
                type="Computer",
                is_active=False,
                is_restricted=False,
            ),
            SpotifyDevice(
                id="device-2",
                name="Living Room",
                type="Speaker",
                is_active=False,
                is_restricted=False,
            ),
        ]

    with pytest.raises(SpotifyNoActiveDeviceError) as exc_info:
        start_playback_with_device_policy(
            token_file=token_file,
            device_file=device_file,
            spotify_uris=("spotify:track:1",),
            start_playback=fake_start_playback,
            fetch_devices=fake_fetch_devices,
        )

    assert playback_calls == [(('spotify:track:1',), None)]
    assert str(exc_info.value) == (
        "No active Spotify device found.\n"
        "Choose a playback device:\n"
        "  1. MacBook [Computer]\n"
        "  2. Living Room [Speaker]\n"
        "Run: /dj device <number>\n"
        "Then run: /dj start"
    )
