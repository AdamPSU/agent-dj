from pathlib import Path

from claude_dj.integrate import claude_code


def test_install_skill_writes_skill_md(tmp_path: Path, monkeypatch) -> None:
    skill_dir = tmp_path / "skills" / "dj"
    skill_path = skill_dir / "SKILL.md"
    monkeypatch.setattr(claude_code, "DJ_SKILL_DIR", skill_dir)
    monkeypatch.setattr(claude_code, "DJ_SKILL_PATH", skill_path)

    out = claude_code.install_skill()
    assert out["ok"] is True
    assert out["action"] in ("installed", "updated")
    assert skill_path.is_file()
    text = skill_path.read_text(encoding="utf-8")
    assert "dj status" in text or "`dj`" in text
    assert "name: dj" in text


def test_install_skill_idempotent(tmp_path: Path, monkeypatch) -> None:
    skill_dir = tmp_path / "skills" / "dj"
    skill_path = skill_dir / "SKILL.md"
    monkeypatch.setattr(claude_code, "DJ_SKILL_DIR", skill_dir)
    monkeypatch.setattr(claude_code, "DJ_SKILL_PATH", skill_path)

    assert claude_code.install_skill()["action"] in ("installed", "updated")
    assert claude_code.install_skill()["action"] == "noop"


def test_uninstall_skill_removes_dir(tmp_path: Path, monkeypatch) -> None:
    skill_dir = tmp_path / "skills" / "dj"
    skill_path = skill_dir / "SKILL.md"
    monkeypatch.setattr(claude_code, "DJ_SKILL_DIR", skill_dir)
    monkeypatch.setattr(claude_code, "DJ_SKILL_PATH", skill_path)
    claude_code.install_skill()
    assert skill_path.is_file()

    out = claude_code.uninstall_skill()
    assert out["ok"] is True
    assert out["action"] == "removed"
    assert not skill_dir.exists()


def test_uninstall_skill_noop_when_missing(tmp_path: Path, monkeypatch) -> None:
    skill_dir = tmp_path / "skills" / "dj"
    skill_path = skill_dir / "SKILL.md"
    monkeypatch.setattr(claude_code, "DJ_SKILL_DIR", skill_dir)
    monkeypatch.setattr(claude_code, "DJ_SKILL_PATH", skill_path)
    out = claude_code.uninstall_skill()
    assert out["ok"] is True
    assert out["action"] == "noop"


def test_skill_is_installed(tmp_path: Path, monkeypatch) -> None:
    skill_dir = tmp_path / "skills" / "dj"
    skill_path = skill_dir / "SKILL.md"
    monkeypatch.setattr(claude_code, "DJ_SKILL_DIR", skill_dir)
    monkeypatch.setattr(claude_code, "DJ_SKILL_PATH", skill_path)
    assert claude_code.skill_is_installed() is False
    claude_code.install_skill()
    assert claude_code.skill_is_installed() is True
