from pathlib import Path


def test_project_dj_command_invokes_installed_cli() -> None:
    command_file = Path(__file__).parents[1] / ".opencode" / "command" / "dj.md"

    content = command_file.read_text(encoding="utf-8")

    assert "dj help" in content
    assert "dj $ARGUMENTS" in content
    assert "uv run" not in content
    assert "project root" not in content.lower()
