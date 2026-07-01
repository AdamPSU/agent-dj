from pathlib import Path

import pytest

from claude_dj.config import (
    DEFAULT_SPOTIFY_REDIRECT_URI,
    MissingConfigError,
    ensure_app_dir,
    get_app_dir,
    get_database_file,
    get_runtime_file,
    get_spotify_config,
    get_spotify_token_file,
)


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
    assert get_spotify_token_file() == app_dir / "spotify-token.json"


def test_ensure_app_dir_creates_directory(tmp_path) -> None:
    app_dir = tmp_path / "claude-dj"

    created = ensure_app_dir(app_dir)

    assert created == app_dir
    assert app_dir.is_dir()


def test_spotify_config_uses_client_id_and_default_redirect(monkeypatch) -> None:
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client-id")
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)

    config = get_spotify_config()

    assert config.client_id == "client-id"
    assert config.redirect_uri == DEFAULT_SPOTIFY_REDIRECT_URI


def test_spotify_config_allows_redirect_override(monkeypatch) -> None:
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:9999/callback")

    config = get_spotify_config()

    assert config.redirect_uri == "http://127.0.0.1:9999/callback"


def test_spotify_config_requires_client_id(monkeypatch) -> None:
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)

    with pytest.raises(MissingConfigError, match="SPOTIFY_CLIENT_ID"):
        get_spotify_config()
