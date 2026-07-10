"""Claude Code narration script generation tests."""

import subprocess

from claude_dj.narration.scripts import build_bridge_prompt, build_intro_prompt, generate_script_with_claude
from claude_dj.storage.db import PlayableTrack


def test_build_intro_prompt_frames_claude_as_personality_heavy_dj() -> None:
    prompt = build_intro_prompt(
        [
            PlayableTrack(1, "spotify:track:1", "Track One", "Artist One"),
            PlayableTrack(2, "spotify:track:2", "Track Two", "Artist Two"),
        ]
    )

    assert "DJ" in prompt
    assert "funny" in prompt
    assert "personality" in prompt
    assert "under 30 words" in prompt
    assert "Track One by Artist One" in prompt
    assert "Track Two by Artist Two" in prompt


def test_build_bridge_prompt_mentions_previous_and_next_blocks() -> None:
    prompt = build_bridge_prompt(
        previous_tracks=[PlayableTrack(1, "spotify:track:1", "Old Track", "Old Artist")],
        next_tracks=[PlayableTrack(2, "spotify:track:2", "New Track", "New Artist")],
    )

    assert "bridge" in prompt.lower()
    assert "Old Track by Old Artist" in prompt
    assert "New Track by New Artist" in prompt


def test_generate_script_with_claude_uses_haiku_print_mode() -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="  We are live in the booth.  \n", stderr="")

    script = generate_script_with_claude("Prompt text", timeout_seconds=12, run=fake_run)

    assert script == "We are live in the booth."
    assert calls == [
        (
            ["claude", "--model", "haiku", "-p", "Prompt text"],
            {
                "capture_output": True,
                "text": True,
                "timeout": 12,
            },
        )
    ]


def test_generate_script_with_claude_does_not_truncate_long_output() -> None:
    long_script = " ".join(f"word{index}" for index in range(40))

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=long_script, stderr="")

    assert generate_script_with_claude("Prompt text", run=fake_run) == long_script


def test_generate_script_with_claude_returns_none_on_failure() -> None:
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="nope")

    assert generate_script_with_claude("Prompt text", run=fake_run) is None


def test_generate_script_with_claude_returns_none_on_timeout() -> None:
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])

    assert generate_script_with_claude("Prompt text", run=fake_run) is None
