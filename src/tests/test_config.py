import json
from pathlib import Path

import pytest

from backend import config


def test_resolve_client_id_from_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "env-id")
    assert config.resolve_spotify_client_id() == "env-id"


def test_resolve_client_id_from_file(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"spotify_client_id": "file-id"}))
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    assert config.resolve_spotify_client_id() == "file-id"


def test_resolve_client_id_missing_raises(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "missing.json")
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    with pytest.raises(config.ConfigError):
        config.resolve_spotify_client_id()


def test_scopes_playback_state_only() -> None:
    assert config.SPOTIFY_SCOPES == "user-read-playback-state"


def test_now_playing_path_under_app_dir() -> None:
    assert config.NOW_PLAYING_PATH == config.APP_DIR / "now_playing.json"


def test_set_spotify_client_id(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    config.set_spotify_client_id("  abc  ")
    data = json.loads((tmp_path / "config.json").read_text())
    assert data["spotify_client_id"] == "abc"


def test_parse_palette_defaults() -> None:
    assert config.parse_palette(None) == config.DEFAULT_PALETTE
    assert config.parse_palette(["#f00"]) == (
        "#FF0000",
        config.DEFAULT_PALETTE[1],
        config.DEFAULT_PALETTE[2],
    )


def test_set_and_load_palette(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    out = config.set_palette(["#abc", "#ffffff", "#1ed760"])
    assert out == ("#AABBCC", "#FFFFFF", "#1ED760")
    assert config.load_palette() == out
    config.clear_palette()
    assert config.load_palette() == config.DEFAULT_PALETTE


def test_set_palette_rejects_bad(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    with pytest.raises(config.ConfigError):
        config.set_palette(["nope", "#fff", "#000"])


def test_pi_placement_defaults_below(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    assert config.load_pi_placement() == "below"
    assert config.parse_pi_placement(None) == "below"
    assert config.parse_pi_placement("nope") == "below"


def test_set_and_load_pi_placement(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    assert config.set_pi_placement("above") == "above"
    assert config.load_pi_placement() == "above"
    assert config.set_pi_placement("below") == "below"
    assert config.load_pi_placement() == "below"


def test_set_pi_placement_rejects_bad(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    with pytest.raises(config.ConfigError):
        config.set_pi_placement("sideways")
