from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from claude_dj.playback.port import PlayerState

EventKind = Literal[
    "same",
    "advanced",
    "foreign",
    "paused",
    "device_gone",
]


@dataclass(frozen=True)
class PlanEvent:
    kind: EventKind
    track_id: str | None = None


class Plan:
    """Virtual queue cursor: where we are in the planned track list."""

    def __init__(self) -> None:
        self.tracks: list[dict[str, Any]] = []
        self.index = 0
        self.expected_id: str | None = None

    def clear(self) -> None:
        """Drop the plan and reset the cursor."""
        self.tracks = []
        self.index = 0
        self.expected_id = None

    def replace(self, tracks: list[dict[str, Any]]) -> None:
        """Install a fresh plan (cold play / empty queue). Cursor at first track."""
        self.tracks = list(tracks)
        self.index = 0
        self.expected_id = str(tracks[0]["spotify_id"]) if tracks else None

    def append(self, tracks: list[dict[str, Any]]) -> None:
        """Extend the plan without moving the cursor."""
        if not tracks:
            return
        if not self.tracks:
            self.replace(tracks)
            return
        self.tracks.extend(tracks)

    def remaining(self) -> list[dict[str, Any]]:
        """Tracks from the cursor through the end of the plan."""
        return self.tracks[self.index :]

    def has_next(self) -> bool:
        """True if a planned track exists after the cursor."""
        return self.index + 1 < len(self.tracks)

    def current(self) -> dict[str, Any] | None:
        """Track at the cursor, or None if the plan is empty."""
        if not self.tracks or self.index >= len(self.tracks):
            return None
        return self.tracks[self.index]

    def move_to(self, track_id: str) -> None:
        """Point the cursor at a planned track id (e.g. after Connect skip)."""
        for i in range(self.index, len(self.tracks)):
            if str(self.tracks[i]["spotify_id"]) == track_id:
                self.index = i
                self.expected_id = track_id
                return
        self.expected_id = track_id

    def advance(self) -> dict[str, Any] | None:
        """Step cursor forward one track; return it, or None if none left."""
        if not self.has_next():
            return None
        self.index += 1
        track = self.tracks[self.index]
        self.expected_id = str(track["spotify_id"])
        return track

    def observe(self, state: PlayerState | None) -> PlanEvent:
        """Compare player state to the plan; return what happened (no side effects)."""
        # Pause/stop never mints — pair-load keeps Connect from going empty.
        if state is None:
            return PlanEvent("device_gone")
        if not state.is_playing or state.track_id is None:
            return PlanEvent("paused")

        track_id = state.track_id
        if track_id == self.expected_id:
            return PlanEvent("same", track_id=track_id)

        planned = {str(t["spotify_id"]) for t in self.remaining()}
        if track_id in planned:
            return PlanEvent("advanced", track_id=track_id)
        return PlanEvent("foreign", track_id=track_id)

