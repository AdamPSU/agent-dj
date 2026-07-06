"""End-user installer for Claude DJ."""

from collections.abc import Callable
from pathlib import Path
import argparse
import shutil
import subprocess
import sys


DEFAULT_INSTALL_SOURCE = "git+https://github.com/AdamPSU/claude-dj-plugin.git"
OPENCODE_COMMAND_TEMPLATE = """---
description: Run Claude DJ lifecycle commands through the installed local CLI.
---

Run the installed Claude DJ CLI.

User command:

/dj `$ARGUMENTS`

Command handling:

- If the command is empty (/dj ``), run `claude-dj status`.
- Otherwise, run `claude-dj $ARGUMENTS`.

Return the command output concisely. Do not add extra explanation unless the command fails.
"""


class InstallerUnavailableError(RuntimeError):
    """Raised when neither supported tool installer is available."""


def build_tool_install_command(
    *,
    source: str = DEFAULT_INSTALL_SOURCE,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """Return the persistent tool-install command for the available backend."""
    if which("uv") is not None:
        return ["uv", "tool", "install", "--force", source]
    if which("pipx") is not None:
        return ["pipx", "install", "--force", source]
    raise InstallerUnavailableError(
        "Claude DJ requires uv or pipx to install. Install uv, then rerun this installer."
    )


def install_opencode_command(*, home: Path | None = None) -> Path:
    """Install the global OpenCode /dj command file."""
    root = home or Path.home()
    command_file = root / ".config" / "opencode" / "command" / "dj.md"
    command_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    command_file.write_text(OPENCODE_COMMAND_TEMPLATE, encoding="utf-8")
    return command_file


def install(
    *,
    source: str = DEFAULT_INSTALL_SOURCE,
    dry_run: bool = False,
    skip_opencode: bool = False,
    which: Callable[[str], str | None] = shutil.which,
    run=subprocess.run,
    home: Path | None = None,
) -> tuple[list[str], Path | None]:
    """Install Claude DJ and its global OpenCode command."""
    command = build_tool_install_command(source=source, which=which)
    command_file = None if skip_opencode else (home or Path.home()) / ".config" / "opencode" / "command" / "dj.md"
    if dry_run:
        return command, command_file

    run(command, check=True)
    if not skip_opencode:
        command_file = install_opencode_command(home=home)
    return command, command_file


def main(argv: list[str] | None = None) -> int:
    """Run the Claude DJ installer."""
    parser = argparse.ArgumentParser(prog="claude-dj-install")
    parser.add_argument("--source", default=DEFAULT_INSTALL_SOURCE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-opencode", action="store_true")
    args = parser.parse_args(argv)

    try:
        command, command_file = install(
            source=args.source,
            dry_run=args.dry_run,
            skip_opencode=args.skip_opencode,
        )
    except InstallerUnavailableError as exc:
        sys.stderr.write(f"{exc}\n")
        sys.stderr.write("Recommended: install uv from https://docs.astral.sh/uv/getting-started/installation/\n")
        return 1

    prefix = "Would run" if args.dry_run else "Ran"
    sys.stdout.write(f"{prefix}: {' '.join(command)}\n")
    if command_file is not None:
        action = "Would install" if args.dry_run else "Installed"
        sys.stdout.write(f"{action} OpenCode command: {command_file}\n")
    if not args.dry_run:
        sys.stdout.write("Next: run /dj spotify-login, then /dj start.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
