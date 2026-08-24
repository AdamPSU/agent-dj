"""Pi extension install (now-playing widget below/above the editor)."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from backend.config import APP_DIR, load_pi_placement

PI_AGENT_DIR = Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent")
EXTENSIONS_DIR = PI_AGENT_DIR / "extensions"
OUR_EXTENSION_NAME = "agent-dj.ts"
OUR_EXTENSION_PATH = EXTENSIONS_DIR / OUR_EXTENSION_NAME
APP_RUNTIME_PATH = APP_DIR / "pi_runtime.json"


def bundled_extension() -> Path:
    return Path(__file__).resolve().parent / "extension.ts"


def resolve_dj_argv(*, json_tick: bool = False) -> list[str]:
    from backend.opencode.statusline import resolve_dj_argv as _resolve

    return _resolve(json_tick=json_tick)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def write_runtime_config(argv: list[str] | None = None) -> Path:
    payload = {
        "version": 1,
        "command": argv or resolve_dj_argv(json_tick=False),
        "placement": load_pi_placement(),
    }
    APP_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(APP_RUNTIME_PATH, payload)
    return APP_RUNTIME_PATH


def is_installed(*, extensions_dir: Path | None = None) -> bool:
    dest = (extensions_dir or EXTENSIONS_DIR) / OUR_EXTENSION_NAME
    return dest.is_file()


def ensure_installed(
    *,
    extensions_dir: Path | None = None,
    extension_src: Path | None = None,
) -> None:
    source = extension_src or bundled_extension()
    if not source.is_file():
        raise FileNotFoundError(f"bundled extension missing: {source}")
    dest_dir = extensions_dir or EXTENSIONS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest_dir / OUR_EXTENSION_NAME)
    write_runtime_config()


def uninstall(*, extensions_dir: Path | None = None) -> None:
    dest = (extensions_dir or EXTENSIONS_DIR) / OUR_EXTENSION_NAME
    dest.unlink(missing_ok=True)
