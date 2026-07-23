import json
from pathlib import Path

import pytest

from backend.opencode import statusline as oc


def test_merge_plugins_preserves_and_appends() -> None:
    assert oc.merge_plugins(["file:///a", "/b"], ["/b", "/c"]) == [
        "file:///a",
        "/b",
        "/c",
    ]


def test_remove_plugins() -> None:
    assert oc.remove_plugins(["/a", "/b", "/a"], ["/a"]) == ["/b"]


def test_remove_plugins_drops_legacy_tsx_entry() -> None:
    root = "file:///tmp/plugins/agent-dj"
    legacy = "file:///tmp/plugins/agent-dj/src/index.tsx"
    old = "file:///tmp/plugins/claude-dj"
    assert oc.remove_plugins([root, legacy, old, "other"], [root]) == ["other"]


def test_discover_tui_paths_includes_project(tmp_path: Path) -> None:
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "tui.json").write_text('{"plugin":[]}\n')
    proj = tmp_path / "proj"
    (proj / ".opencode").mkdir(parents=True)
    (proj / ".git").mkdir()
    (proj / ".opencode" / "tui.json").write_text('{"plugin":["only-goal"]}\n')
    paths = oc.discover_tui_paths(config_dir=global_dir, cwd=proj)
    assert paths[0] == global_dir / "tui.json"
    assert any(p.name == "tui.json" and ".opencode" in p.parts for p in paths)


def test_write_runtime_config(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "opencode_runtime.json"
    monkeypatch.setattr(oc, "APP_RUNTIME_PATH", runtime)
    monkeypatch.setattr(oc, "APP_DIR", tmp_path)
    path = oc.write_runtime_config(argv=["/x/dj", "tick", "--json"])
    assert path == runtime
    data = json.loads(path.read_text())
    assert data["command"] == ["/x/dj", "tick", "--json"]
    assert data["env"]["NO_COLOR"] == "1"


def test_ensure_installed_happy(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "config"
    config.mkdir()
    plugins = config / "plugins"
    plugin_src = tmp_path / "bundled"
    (plugin_src / "src").mkdir(parents=True)
    (plugin_src / "package.json").write_text("{}")
    (plugin_src / "src" / "index.tsx").write_text("// x")
    runtime = tmp_path / "runtime.json"
    monkeypatch.setattr(oc, "APP_RUNTIME_PATH", runtime)
    monkeypatch.setattr(oc, "APP_DIR", tmp_path)
    monkeypatch.setattr(
        oc, "resolve_dj_argv", lambda **_k: ["/bin/dj", "tick", "--json"]
    )

    oc.ensure_installed(
        config_dir=config,
        plugins_dir=plugins,
        plugin_src=plugin_src,
        cwd=tmp_path,
    )

    our = plugins / "agent-dj"
    assert (our / "src" / "index.tsx").is_file()
    assert not (our / "runtime.json").exists()
    data = json.loads(runtime.read_text())
    assert data["command"] == ["/bin/dj", "tick", "--json"]
    tui = json.loads((config / "tui.json").read_text())
    entry = oc.plugin_entry(our)
    assert entry in tui["plugin"]
    assert oc.is_installed(config_dir=config, plugins_dir=plugins)


def test_ensure_installed_updates_project_tui(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "config"
    config.mkdir()
    plugins = config / "plugins"
    plugin_src = tmp_path / "bundled"
    (plugin_src / "src").mkdir(parents=True)
    (plugin_src / "package.json").write_text("{}")
    (plugin_src / "src" / "index.tsx").write_text("// x")
    proj = tmp_path / "proj"
    (proj / ".opencode").mkdir(parents=True)
    (proj / ".git").mkdir()
    project_tui = proj / ".opencode" / "tui.json"
    project_tui.write_text(
        json.dumps({"plugin": ["@prevalentware/opencode-goal-plugin"]}) + "\n"
    )
    runtime = tmp_path / "runtime.json"
    monkeypatch.setattr(oc, "APP_RUNTIME_PATH", runtime)
    monkeypatch.setattr(oc, "APP_DIR", tmp_path)
    monkeypatch.setattr(
        oc, "resolve_dj_argv", lambda **_k: ["/bin/dj", "tick", "--json"]
    )

    oc.ensure_installed(
        config_dir=config,
        plugins_dir=plugins,
        plugin_src=plugin_src,
        cwd=proj,
    )
    proj_plugins = json.loads(project_tui.read_text())["plugin"]
    assert "@prevalentware/opencode-goal-plugin" in proj_plugins
    assert any("agent-dj" in str(p) for p in proj_plugins)
    assert not any("claude-dj" in str(p) for p in proj_plugins)


def test_ensure_installed_missing_bundle_raises(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, OSError)):
        oc.ensure_installed(
            config_dir=tmp_path,
            plugins_dir=tmp_path / "plugins",
            plugin_src=tmp_path / "missing",
            cwd=tmp_path,
        )


def test_uninstall_removes_our_entry(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "config"
    config.mkdir()
    plugins = config / "plugins"
    plugin_src = tmp_path / "bundled"
    (plugin_src / "src").mkdir(parents=True)
    (plugin_src / "package.json").write_text("{}")
    (plugin_src / "src" / "index.tsx").write_text("// x")
    runtime = tmp_path / "runtime.json"
    monkeypatch.setattr(oc, "APP_RUNTIME_PATH", runtime)
    monkeypatch.setattr(oc, "APP_DIR", tmp_path)
    monkeypatch.setattr(
        oc, "resolve_dj_argv", lambda **_k: ["/bin/dj", "tick", "--json"]
    )
    oc.ensure_installed(
        config_dir=config,
        plugins_dir=plugins,
        plugin_src=plugin_src,
        cwd=tmp_path,
    )
    oc.uninstall(config_dir=config, plugins_dir=plugins, cwd=tmp_path)
    tui = json.loads((config / "tui.json").read_text())
    assert not any("agent-dj" in str(p) for p in tui.get("plugin", []))
    assert not any("claude-dj" in str(p) for p in tui.get("plugin", []))
    assert not oc.is_installed(config_dir=config, plugins_dir=plugins)


def test_uninstall_noop_when_absent(tmp_path: Path) -> None:
    (tmp_path / "tui.json").write_text('{"plugin":[]}\n')
    oc.uninstall(config_dir=tmp_path, plugins_dir=tmp_path / "plugins", cwd=tmp_path)
