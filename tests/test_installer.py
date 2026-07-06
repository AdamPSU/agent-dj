import importlib
import importlib.util
from pathlib import Path
import tomllib

import pytest


def load_installer():
    assert importlib.util.find_spec("claude_dj.installer") is not None
    return importlib.import_module("claude_dj.installer")


def test_installer_prefers_uv_tool_install() -> None:
    installer = load_installer()

    def fake_which(name: str) -> str | None:
        return "/usr/local/bin/uv" if name == "uv" else None

    command = installer.build_tool_install_command(
        source="git+https://github.com/AdamPSU/claude-dj-plugin.git",
        which=fake_which,
    )

    assert command == [
        "uv",
        "tool",
        "install",
        "--force",
        "git+https://github.com/AdamPSU/claude-dj-plugin.git",
    ]


def test_installer_falls_back_to_pipx_install() -> None:
    installer = load_installer()

    def fake_which(name: str) -> str | None:
        return "/usr/local/bin/pipx" if name == "pipx" else None

    command = installer.build_tool_install_command(
        source="git+https://github.com/AdamPSU/claude-dj-plugin.git",
        which=fake_which,
    )

    assert command == [
        "pipx",
        "install",
        "--force",
        "git+https://github.com/AdamPSU/claude-dj-plugin.git",
    ]


def test_installer_errors_when_no_supported_tool_installer_exists() -> None:
    installer = load_installer()

    with pytest.raises(installer.InstallerUnavailableError, match="uv or pipx"):
        installer.build_tool_install_command(
            source="git+https://github.com/AdamPSU/claude-dj-plugin.git",
            which=lambda name: None,
        )


def test_installer_writes_global_opencode_command(tmp_path) -> None:
    installer = load_installer()

    command_file = installer.install_opencode_command(home=tmp_path)

    assert command_file == tmp_path / ".config" / "opencode" / "command" / "dj.md"
    content = command_file.read_text(encoding="utf-8")
    assert "claude-dj status" in content
    assert "claude-dj $ARGUMENTS" in content
    assert "uv run" not in content


def test_default_install_source_uses_git_url() -> None:
    installer = load_installer()

    assert installer.DEFAULT_INSTALL_SOURCE == "git+https://github.com/AdamPSU/claude-dj-plugin.git"


def test_package_exposes_installer_console_script() -> None:
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    assert metadata["project"]["scripts"]["claude-dj-install"] == "claude_dj.installer:main"
