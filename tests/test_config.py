from pathlib import Path

import pytest

import claude_dj.config as config_module
from claude_dj.config import (
    DEFAULT_ELEVENLABS_MODEL_ID,
    DEFAULT_ELEVENLABS_OUTPUT_FORMAT,
    DEFAULT_SPOTIFY_REDIRECT_URI,
    LOCAL_MUQ_DIMENSIONS,
    LOCAL_MUQ_MODEL_NAME,
    MissingConfigError,
    ensure_app_dir,
    ensure_narration_dir,
    get_app_dir,
    get_database_file,
    get_embedding_config,
    get_narration_config,
    get_narration_dir,
    get_runtime_file,
    get_spotify_config,
    get_spotify_token_file,
)


@pytest.fixture(autouse=True)
def isolate_package_env_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config_module, "PACKAGE_ENV_FILE", tmp_path / "missing-package.env")
    monkeypatch.delenv("CLAUDE_DJ_ENV_FILE", raising=False)


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
    assert get_narration_dir() == app_dir / "narration"


def test_ensure_app_dir_creates_directory(tmp_path) -> None:
    app_dir = tmp_path / "claude-dj"

    created = ensure_app_dir(app_dir)

    assert created == app_dir
    assert app_dir.is_dir()


def test_ensure_narration_dir_creates_directory(tmp_path) -> None:
    app_dir = tmp_path / "claude-dj"

    created = ensure_narration_dir(app_dir)

    assert created == app_dir / "narration"
    assert created.is_dir()


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


def test_embedding_config_defaults_to_local_muq_only() -> None:
    config = get_embedding_config()

    assert config.model_name == LOCAL_MUQ_MODEL_NAME
    assert config.dimensions == LOCAL_MUQ_DIMENSIONS
    assert set(config.__dataclass_fields__) == {"model_name", "model_version", "dimensions"}


def test_narration_config_uses_elevenlabs_env_and_v3_default(monkeypatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "elevenlabs-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice-id")
    monkeypatch.delenv("ELEVENLABS_MODEL_ID", raising=False)
    monkeypatch.delenv("ELEVENLABS_OUTPUT_FORMAT", raising=False)

    config = get_narration_config()

    assert config is not None
    assert config.elevenlabs_api_key == "elevenlabs-key"
    assert config.elevenlabs_voice_id == "voice-id"
    assert config.elevenlabs_model_id == DEFAULT_ELEVENLABS_MODEL_ID
    assert config.elevenlabs_output_format == DEFAULT_ELEVENLABS_OUTPUT_FORMAT


def test_narration_config_loads_app_env_file(monkeypatch, tmp_path) -> None:
    app_dir = tmp_path / "claude-dj-home"
    app_dir.mkdir()
    (app_dir / ".env").write_text(
        "ELEVENLABS_API_KEY=env-file-key\nELEVENLABS_VOICE_ID=env-file-voice\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(app_dir))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)

    config = get_narration_config()

    assert config is not None
    assert config.elevenlabs_api_key == "env-file-key"
    assert config.elevenlabs_voice_id == "env-file-voice"


def test_narration_config_does_not_override_shell_env_with_env_file(monkeypatch, tmp_path) -> None:
    app_dir = tmp_path / "claude-dj-home"
    app_dir.mkdir()
    (app_dir / ".env").write_text(
        "ELEVENLABS_API_KEY=env-file-key\nELEVENLABS_VOICE_ID=env-file-voice\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(app_dir))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "shell-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "shell-voice")

    config = get_narration_config()

    assert config is not None
    assert config.elevenlabs_api_key == "shell-key"
    assert config.elevenlabs_voice_id == "shell-voice"


def test_narration_config_loads_package_env_file(monkeypatch, tmp_path) -> None:
    package_env = tmp_path / ".env"
    package_env.write_text(
        "ELEVENLABS_API_KEY=package-key\nELEVENLABS_VOICE_ID=package-voice\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(tmp_path / "missing-app-dir"))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    monkeypatch.setattr(config_module, "PACKAGE_ENV_FILE", package_env, raising=False)

    config = get_narration_config()

    assert config is not None
    assert config.elevenlabs_api_key == "package-key"
    assert config.elevenlabs_voice_id == "package-voice"


def test_narration_config_is_disabled_without_required_elevenlabs_env(monkeypatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice-id")

    assert get_narration_config() is None
