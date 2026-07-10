"""Generate short DJ narration scripts with Claude Code."""

from collections.abc import Callable, Sequence
import subprocess

from claude_dj.storage.db import PlayableTrack


SCRIPT_TIMEOUT_SECONDS = 45.0


def build_intro_prompt(tracks: Sequence[PlayableTrack]) -> str:
    """Build a prompt for the startup DJ intro."""
    return _script_prompt(
        "Introduce Claude DJ and hype the first block before the music starts.",
        "First block",
        tracks,
    )


def build_bridge_prompt(previous_tracks: Sequence[PlayableTrack], next_tracks: Sequence[PlayableTrack]) -> str:
    """Build a prompt for a between-block DJ bridge."""
    return "\n".join(
        [
            "You are Claude DJ, a funny, personality-heavy radio DJ.",
            "Write one seamless bridge from the previous block into the next block.",
            "Keep it under 30 words. Return only the words the DJ should say.",
            f"Previous block: {_track_list(previous_tracks)}",
            f"Next block: {_track_list(next_tracks)}",
        ]
    )


def generate_script_with_claude(
    prompt: str,
    *,
    timeout_seconds: float = SCRIPT_TIMEOUT_SECONDS,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str | None:
    """Generate a narration script using Claude Code print mode."""
    try:
        result = run(
            ["claude", "--model", "haiku", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0:
        return None
    script = " ".join(result.stdout.split())
    return script or None


def _script_prompt(instruction: str, label: str, tracks: Sequence[PlayableTrack]) -> str:
    return "\n".join(
        [
            "You are Claude DJ, a funny, personality-heavy radio DJ.",
            instruction,
            "Keep it under 30 words. Return only the words the DJ should say.",
            f"{label}: {_track_list(tracks)}",
        ]
    )


def _track_list(tracks: Sequence[PlayableTrack]) -> str:
    if not tracks:
        return "unknown tracks"
    return "; ".join(f"{track.title} by {track.artist_name}" for track in tracks)
