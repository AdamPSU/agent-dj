from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class PlayerState:
    is_playing: bool
    progress_ms: int | None
    duration_ms: int | None
    track_id: str | None
    device_id: str | None = None
    context_uri: str | None = None
    name: str | None = None
    artists: str | None = None

    @property
    def time_remaining_ms(self) -> int | None:
        if self.progress_ms is None or self.duration_ms is None:
            return None
        return max(0, int(self.duration_ms) - int(self.progress_ms))


class PlaybackPort(Protocol):
    def start_block(self, tracks: list[dict[str, Any]]) -> None:
        """Load a planned block (all URIs) and start the first track."""

    def play_uri(self, spotify_id: str, *, device_id: str | None = None) -> None:
        """Start a single track on the active (or given) device."""

    def get_state(self) -> PlayerState | None:
        """Current Spotify player state, or None if unavailable."""


class FakePlayback:
    """In-memory player for tests: multi-URI block + controllable now-playing."""

    def __init__(self) -> None:
        self.last_block: list[dict[str, Any]] | None = None
        self.last_uris: list[str] = []
        self.start_count = 0
        self.play_uri_calls: list[str] = []
        self._state: PlayerState | None = None
        self.queue: list[dict[str, Any]] = []

    def start_block(self, tracks: list[dict[str, Any]]) -> None:
        self.last_block = list(tracks)
        self.queue = list(tracks)
        self.last_uris = [str(t["spotify_id"]) for t in tracks]
        self.start_count += 1
        if tracks:
            sid = str(tracks[0]["spotify_id"])
            self.play_uri_calls.append(sid)
            self._state = PlayerState(
                is_playing=True,
                progress_ms=0,
                duration_ms=180_000,
                track_id=sid,
                device_id="fake-device",
                context_uri=None,
            )

    def play_uri(self, spotify_id: str, *, device_id: str | None = None) -> None:
        self.play_uri_calls.append(spotify_id)
        self.last_uris = [spotify_id]
        self._state = PlayerState(
            is_playing=True,
            progress_ms=0,
            duration_ms=180_000,
            track_id=spotify_id,
            device_id=device_id or "fake-device",
            context_uri=None,
        )

    def get_state(self) -> PlayerState | None:
        return self._state

    def set_state(
        self,
        *,
        track_id: str | None,
        is_playing: bool = True,
        progress_ms: int = 0,
        duration_ms: int = 180_000,
        device_id: str | None = "fake-device",
        name: str | None = None,
        artists: str | None = None,
    ) -> None:
        """Test helper: simulate Spotify player observation."""
        if track_id is None and not is_playing:
            self._state = None
            return
        self._state = PlayerState(
            is_playing=is_playing,
            progress_ms=progress_ms,
            duration_ms=duration_ms,
            track_id=track_id,
            device_id=device_id,
            context_uri=None,
            name=name,
            artists=artists,
        )


class SpotifyPlayback:
    """PlaybackPort backed by Spotify Connect Player API."""

    def __init__(self) -> None:
        self.last_block: list[dict[str, Any]] | None = None
        self.last_uris: list[str] = []
        self.start_count = 0

    def start_block(self, tracks: list[dict[str, Any]]) -> None:
        """Load the full block so Connect skip advances within the plan."""
        from claude_dj.adapters import spotify

        self.last_block = list(tracks)
        self.start_count += 1
        if not tracks:
            self.last_uris = []
            return
        try:
            spotify.set_shuffle(False)
            spotify.set_repeat("off")
        except Exception:
            pass
        uris = [f"spotify:track:{t['spotify_id']}" for t in tracks]
        self.last_uris = [str(t["spotify_id"]) for t in tracks]
        target = spotify.load_preferred_device_id()
        spotify.start_playback_uris(uris, device_id=target)

    def play_uri(self, spotify_id: str, *, device_id: str | None = None) -> None:
        from claude_dj.adapters import spotify

        uri = f"spotify:track:{spotify_id}"
        self.last_uris = [spotify_id]
        target = device_id or spotify.load_preferred_device_id()
        spotify.start_playback_uris([uri], device_id=target)

    def get_state(self) -> PlayerState | None:
        from claude_dj.adapters import spotify

        raw = spotify.get_playback_state()
        if not raw:
            return None
        item = raw.get("item") or {}
        device = raw.get("device") or {}
        context = raw.get("context") or {}
        track_id = item.get("id")
        artists = ", ".join(
            str(a.get("name") or "")
            for a in (item.get("artists") or [])
            if isinstance(a, dict)
        ).strip(", ")
        return PlayerState(
            is_playing=bool(raw.get("is_playing")),
            progress_ms=raw.get("progress_ms"),
            duration_ms=item.get("duration_ms"),
            track_id=str(track_id) if track_id else None,
            device_id=device.get("id"),
            context_uri=context.get("uri"),
            name=str(item.get("name") or "") or None,
            artists=artists or None,
        )
