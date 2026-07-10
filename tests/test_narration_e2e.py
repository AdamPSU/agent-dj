"""Opt-in real API checks for Claude DJ narration providers."""

import os
import subprocess

import miniaudio
import pytest

from claude_dj.adapters.elevenlabs import synthesize_speech_to_file
from claude_dj.config import get_narration_config


pytestmark = pytest.mark.skipif(
    os.environ.get("CLAUDE_DJ_E2E") != "1",
    reason="real Claude Code and ElevenLabs API calls are opt-in",
)


def test_claude_haiku_reachability() -> None:
    result = subprocess.run(
        ["claude", "--model", "haiku", "-p", "Reply with OK only."],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "OK"


def test_elevenlabs_voice_streams_audio_that_decodes(tmp_path) -> None:
    config = get_narration_config()
    assert config is not None

    audio_file = synthesize_speech_to_file(
        "Claude DJ end to end voice check.",
        tmp_path / "voice.mp3",
        config,
    )
    decoded = miniaudio.decode_file(str(audio_file))

    assert audio_file.stat().st_size > 1000
    assert decoded.sample_rate > 0
    assert decoded.nchannels > 0
    assert decoded.duration > 0
