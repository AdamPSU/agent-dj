import json
from pathlib import Path

import pytest

from backend.pi import statusline as pi


def test_ensure_installed_copies_extension(tmp_path: Path, monkeypatch) -> None:
    ext_dir = tmp_path / "extensions"
    src = tmp_path / "bundled.ts"
    src.write_text("// agent-dj\nsetWidget\n")
    runtime = tmp_path / "pi_runtime.json"
    monkeypatch.setattr(pi, "APP_RUNTIME_PATH", runtime)
    monkeypatch.setattr(pi, "APP_DIR", tmp_path)
    monkeypatch.setattr(
        pi, "resolve_dj_argv", lambda **_k: ["/bin/dj", "tick"]
    )

    pi.ensure_installed(extensions_dir=ext_dir, extension_src=src)

    dest = ext_dir / "agent-dj.ts"
    assert dest.is_file()
    assert "setWidget" in dest.read_text()
    data = json.loads(runtime.read_text())
    assert data["command"] == ["/bin/dj", "tick"]
    assert data["placement"] == "below"
    assert pi.is_installed(extensions_dir=ext_dir)


def test_ensure_installed_uses_saved_placement(
    tmp_path: Path, monkeypatch
) -> None:
    from backend import config as app_config

    ext_dir = tmp_path / "extensions"
    src = tmp_path / "bundled.ts"
    src.write_text("// x\n")
    runtime = tmp_path / "pi_runtime.json"
    monkeypatch.setattr(pi, "APP_RUNTIME_PATH", runtime)
    monkeypatch.setattr(pi, "APP_DIR", tmp_path)
    monkeypatch.setattr(app_config, "APP_DIR", tmp_path)
    monkeypatch.setattr(app_config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(
        pi, "resolve_dj_argv", lambda **_k: ["/bin/dj", "tick"]
    )
    app_config.set_pi_placement("above")

    pi.ensure_installed(extensions_dir=ext_dir, extension_src=src)
    data = json.loads(runtime.read_text())
    assert data["placement"] == "above"


def test_ensure_installed_missing_bundle_raises(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, OSError)):
        pi.ensure_installed(
            extensions_dir=tmp_path / "extensions",
            extension_src=tmp_path / "missing.ts",
        )


def test_uninstall_removes_extension(tmp_path: Path, monkeypatch) -> None:
    ext_dir = tmp_path / "extensions"
    src = tmp_path / "bundled.ts"
    src.write_text("// x\n")
    runtime = tmp_path / "pi_runtime.json"
    monkeypatch.setattr(pi, "APP_RUNTIME_PATH", runtime)
    monkeypatch.setattr(pi, "APP_DIR", tmp_path)
    monkeypatch.setattr(
        pi, "resolve_dj_argv", lambda **_k: ["/bin/dj", "tick"]
    )
    pi.ensure_installed(extensions_dir=ext_dir, extension_src=src)
    pi.uninstall(extensions_dir=ext_dir)
    assert not (ext_dir / "agent-dj.ts").exists()
    assert not pi.is_installed(extensions_dir=ext_dir)


def test_uninstall_noop_when_absent(tmp_path: Path) -> None:
    pi.uninstall(extensions_dir=tmp_path / "extensions")
