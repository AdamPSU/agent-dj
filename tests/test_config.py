import pytest

from claude_dj import config


def test_resolve_client_id_prefers_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    config.save_app_config({"spotify_client_id": "from-file"})
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "from-env")
    assert config.resolve_spotify_client_id() == "from-env"


def test_resolve_client_id_uses_config_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    config.save_app_config({"spotify_client_id": "from-file"})
    assert config.resolve_spotify_client_id() == "from-file"


def test_resolve_client_id_missing_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    with pytest.raises(config.ConfigError, match="dj setup"):
        config.resolve_spotify_client_id()


def test_save_and_load_app_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    config.save_app_config({"spotify_client_id": "abc123"})
    assert config.load_app_config() == {"spotify_client_id": "abc123"}
    mode = (tmp_path / "config.json").stat().st_mode & 0o777
    assert mode == 0o600


def test_set_spotify_client_id_merges(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    config.save_app_config({"other": 1})
    config.set_spotify_client_id("new-id")
    data = config.load_app_config()
    assert data["spotify_client_id"] == "new-id"
    assert data["other"] == 1
