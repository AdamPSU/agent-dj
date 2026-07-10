"""Local narration audio playback tests."""

import pytest

from claude_dj.audio.local_playback import LocalPlaybackError, play_audio_file


def test_play_audio_file_requires_existing_file(tmp_path) -> None:
    with pytest.raises(LocalPlaybackError, match="does not exist"):
        play_audio_file(tmp_path / "missing.mp3")


def test_play_audio_file_delegates_to_backend(tmp_path) -> None:
    audio_file = tmp_path / "speech.mp3"
    audio_file.write_bytes(b"audio")
    calls = []

    def fake_backend(path, timeout_seconds):
        calls.append((path, timeout_seconds))

    play_audio_file(audio_file, timeout_seconds=5.0, backend=fake_backend)

    assert calls == [(audio_file, 5.0)]


def test_play_audio_file_wraps_backend_failure(tmp_path) -> None:
    audio_file = tmp_path / "speech.mp3"
    audio_file.write_bytes(b"audio")

    def fake_backend(path, timeout_seconds):
        raise RuntimeError("device unavailable")

    with pytest.raises(LocalPlaybackError, match="local audio playback failed"):
        play_audio_file(audio_file, backend=fake_backend)
