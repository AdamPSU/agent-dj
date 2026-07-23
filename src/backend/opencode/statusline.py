"""OpenCode TUI plugin install (agent-dj chip only)."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from backend.config import APP_DIR

OPENCODE_CONFIG_DIR = Path.home() / ".config" / "opencode"
PLUGINS_DIR = OPENCODE_CONFIG_DIR / "plugins"
PLUGIN_NAME = "agent-dj"
OUR_PLUGIN_DIR = PLUGINS_DIR / PLUGIN_NAME
APP_RUNTIME_PATH = APP_DIR / "opencode_runtime.json"
TUI_SCHEMA = "https://opencode.ai/tui.json"


def bundled_plugin_root() -> Path:
    return Path(__file__).resolve().parent / "plugin"


def resolve_dj_argv(*, json_tick: bool = True) -> list[str]:
    """Absolute argv for tick. Prefer real tool install over project .venv."""
    home = Path.home()
    candidates: list[Path] = []
    which = shutil.which("dj")
    if which:
        candidates.append(Path(which).resolve())
    candidates.append(home / ".local" / "bin" / "dj")
    candidates.append(
        home / ".local" / "share" / "uv" / "tools" / "agent-dj" / "bin" / "dj"
    )
    candidates.append(Path(sys.executable).resolve().parent / "dj")
    tail = ["tick", "--json"] if json_tick else ["tick"]

    def usable(path: Path) -> bool:
        return path.is_file() and os.access(path, os.X_OK)

    for path in candidates:
        if usable(path) and ".venv" not in path.parts:
            return [str(path), *tail]
    for path in candidates:
        if usable(path):
            return [str(path), *tail]
    return [str(Path(sys.executable).resolve()), "-m", "backend.cli", *tail]


def plugin_entry(dest: Path | None = None) -> str:
    return (dest or OUR_PLUGIN_DIR).resolve().as_uri()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_runtime_config(argv: list[str] | None = None) -> Path:
    from backend.config import load_palette

    artist, song, time_c = load_palette()
    payload = {
        "version": 1,
        "command": argv or resolve_dj_argv(json_tick=True),
        "env": {"NO_COLOR": "1"},
        "palette": [artist, song, time_c],
    }
    APP_DIR.mkdir(parents=True, exist_ok=True)
    APP_RUNTIME_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        APP_RUNTIME_PATH.chmod(0o600)
    except OSError:
        pass
    return APP_RUNTIME_PATH


def resolve_tui_path(config_dir: Path | None = None) -> Path:
    base = config_dir or OPENCODE_CONFIG_DIR
    for name in ("tui.json", "tui.jsonc"):
        path = base / name
        if path.is_file():
            return path
    return base / "tui.json"


def discover_tui_paths(
    *,
    config_dir: Path | None = None,
    cwd: Path | None = None,
) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen:
            return
        seen.add(key)
        paths.append(path)

    add(resolve_tui_path(config_dir))
    cur = (cwd or Path.cwd()).resolve()
    for parent in [cur, *cur.parents]:
        for name in ("tui.json", "tui.jsonc"):
            candidate = parent / ".opencode" / name
            if candidate.is_file():
                add(candidate)
        if (parent / ".git").is_dir() or parent == Path.home():
            break
    return paths


def merge_plugins(plugins: list[Any], entries: list[str]) -> list[Any]:
    out: list[Any] = list(plugins) if isinstance(plugins, list) else []
    have = {str(p) for p in out}
    for entry in entries:
        if entry not in have:
            out.append(entry)
            have.add(entry)
    return out


def remove_plugins(plugins: list[Any], entries: list[str]) -> list[Any]:
    drop = {str(e) for e in entries}
    for e in list(drop):
        if e.endswith(f"/{PLUGIN_NAME}"):
            drop.add(e.rstrip("/") + "/src/index.tsx")
        if e.endswith(f"/{PLUGIN_NAME}/src/index.tsx"):
            drop.add(e[: -len("/src/index.tsx")])
    return [p for p in plugins if str(p) not in drop]


def _merge_entry(tui_path: Path, entry: str) -> None:
    data = _read_json(tui_path) or {}
    plugins = data.get("plugin")
    if not isinstance(plugins, list):
        plugins = []
    data["plugin"] = merge_plugins(plugins, [entry])
    if "$schema" not in data:
        data["$schema"] = TUI_SCHEMA
    _write_json(tui_path, data)


def _drop_entry(tui_path: Path, entry: str) -> None:
    if not tui_path.is_file():
        return
    data = _read_json(tui_path) or {}
    plugins = data.get("plugin")
    if not isinstance(plugins, list):
        return
    data["plugin"] = remove_plugins(plugins, [entry])
    _write_json(tui_path, data)


def sync_our_plugin(*, dest: Path | None = None, src: Path | None = None) -> Path:
    source = src or bundled_plugin_root()
    target = dest or OUR_PLUGIN_DIR
    if not source.is_dir():
        raise FileNotFoundError(f"bundled plugin missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


def is_installed(
    *,
    config_dir: Path | None = None,
    plugins_dir: Path | None = None,
) -> bool:
    plugins_dir = plugins_dir or (
        (config_dir / "plugins") if config_dir else PLUGINS_DIR
    )
    entry = plugin_entry(plugins_dir / PLUGIN_NAME)
    tui = _read_json(resolve_tui_path(config_dir)) or {}
    plugins = tui.get("plugin")
    if not isinstance(plugins, list):
        return False
    have = {str(p) for p in plugins}
    return entry in have


def ensure_installed(
    *,
    config_dir: Path | None = None,
    plugins_dir: Path | None = None,
    plugin_src: Path | None = None,
    cwd: Path | None = None,
) -> None:
    config_dir = config_dir or OPENCODE_CONFIG_DIR
    plugins_dir = plugins_dir or (config_dir / "plugins")
    target = sync_our_plugin(dest=plugins_dir / PLUGIN_NAME, src=plugin_src)
    write_runtime_config()
    entry = plugin_entry(target)
    for path in discover_tui_paths(config_dir=config_dir, cwd=cwd):
        _merge_entry(path, entry)


def uninstall(
    *,
    config_dir: Path | None = None,
    plugins_dir: Path | None = None,
    cwd: Path | None = None,
) -> None:
    config_dir = config_dir or OPENCODE_CONFIG_DIR
    plugins_dir = plugins_dir or (config_dir / "plugins")
    entry = plugin_entry(plugins_dir / PLUGIN_NAME)
    for path in discover_tui_paths(config_dir=config_dir, cwd=cwd):
        _drop_entry(path, entry)
