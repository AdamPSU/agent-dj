import json
import os
from pathlib import Path
from typing import Any

APP_DIR = Path.home() / ".agent-dj"
_LEGACY_APP_DIR = Path.home() / ".claude-dj"

if not APP_DIR.exists() and _LEGACY_APP_DIR.is_dir():
    try:
        _LEGACY_APP_DIR.rename(APP_DIR)
    except OSError:
        pass

SPOTIFY_TOKEN_PATH = APP_DIR / "spotify_tokens.json"
NOW_PLAYING_PATH = APP_DIR / "now_playing.json"
CONFIG_PATH = APP_DIR / "config.json"

SPOTIFY_SCOPES = "user-read-playback-state"
SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"


class ConfigError(RuntimeError):
    """Missing or invalid durable app configuration."""


def load_app_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_app_config(data: dict[str, Any]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    CONFIG_PATH.chmod(0o600)


def set_spotify_client_id(client_id: str) -> None:
    data = load_app_config()
    data["spotify_client_id"] = client_id.strip()
    save_app_config(data)


def resolve_spotify_client_id() -> str:
    env = (os.environ.get("SPOTIFY_CLIENT_ID") or "").strip()
    if env:
        return env
    file_id = str(load_app_config().get("spotify_client_id") or "").strip()
    if file_id:
        return file_id
    raise ConfigError("Spotify client ID not configured; run: dj auth")
