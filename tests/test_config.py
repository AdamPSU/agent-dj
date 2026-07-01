from pathlib import Path

from claude_dj.config import ensure_app_dir, get_app_dir, get_database_file, get_runtime_file


def test_app_dir_defaults_to_home(monkeypatch) -> None:
    monkeypatch.delenv("CLAUDE_DJ_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: Path("/Users/tester"))

    assert get_app_dir() == Path("/Users/tester/.claude-dj")


def test_app_dir_can_be_overridden(monkeypatch, tmp_path) -> None:
    app_dir = tmp_path / "runtime-home"
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(app_dir))

    assert get_app_dir() == app_dir
    assert get_runtime_file() == app_dir / "runtime.json"
    assert get_database_file() == app_dir / "claude-dj.sqlite3"


def test_ensure_app_dir_creates_directory(tmp_path) -> None:
    app_dir = tmp_path / "claude-dj"

    created = ensure_app_dir(app_dir)

    assert created == app_dir
    assert app_dir.is_dir()
