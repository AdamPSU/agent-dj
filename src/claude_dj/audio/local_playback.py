"""Local audio playback for generated DJ narration."""

from collections.abc import Callable
from pathlib import Path
import time


class LocalPlaybackError(RuntimeError):
    """Raised when local narration audio cannot be played."""


PlaybackBackend = Callable[[Path, float], None]


def play_audio_file(
    audio_file: Path,
    *,
    timeout_seconds: float = 5.0,
    backend: PlaybackBackend | None = None,
) -> None:
    """Play an audio file through the local machine's default output device."""
    if not audio_file.is_file():
        raise LocalPlaybackError(f"Audio file does not exist: {audio_file}")

    player = backend or _play_with_miniaudio
    try:
        player(audio_file, timeout_seconds)
    except LocalPlaybackError:
        raise
    except Exception as exc:
        raise LocalPlaybackError("local audio playback failed") from exc


def _play_with_miniaudio(audio_file: Path, timeout_seconds: float) -> None:
    import miniaudio

    decoded = miniaudio.decode_file(str(audio_file))
    stream = miniaudio.stream_file(str(audio_file))
    with miniaudio.PlaybackDevice(
        output_format=decoded.sample_format,
        nchannels=decoded.nchannels,
        sample_rate=decoded.sample_rate,
    ) as device:
        device.start(stream)
        time.sleep(float(decoded.duration))
        device.stop()
