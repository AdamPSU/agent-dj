"""Install the personal Claude Code /dj skill."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

from claude_dj.config import DJ_SKILL_DIR, DJ_SKILL_PATH

MARKER = "name: dj"


def _skill_template() -> str:
    path = resources.files("claude_dj.integrate.templates").joinpath("dj.SKILL.md")
    return path.read_text(encoding="utf-8")


def skill_is_installed(*, skill_path: Path | None = None) -> bool:
    path = skill_path or DJ_SKILL_PATH
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return MARKER in text and (
        "dj status" in text
        or "claude-dj" in text
        or "`dj`" in text
        or "dj jam" in text
        or "dj attach" in text
    )


def install_skill(
    *,
    skill_dir: Path | None = None,
    skill_path: Path | None = None,
) -> dict[str, Any]:
    """Write ~/.claude/skills/dj/SKILL.md from the packaged template."""
    directory = skill_dir or DJ_SKILL_DIR
    path = skill_path or DJ_SKILL_PATH
    body = _skill_template()
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == body:
            return {"ok": True, "action": "noop", "path": str(path)}
        directory.mkdir(parents=True, exist_ok=True)
        existed = path.is_file()
        path.write_text(body, encoding="utf-8")
        return {
            "ok": True,
            "action": "updated" if existed else "installed",
            "path": str(path),
        }
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
