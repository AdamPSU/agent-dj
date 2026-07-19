import json
import os
from pathlib import Path
from typing import Any

HOST = "127.0.0.1"
PORT = 8787
BASE_URL = f"http://{HOST}:{PORT}"

APP_DIR = Path.home() / ".claude-dj"
DB_PATH = APP_DIR / "catalog.db"
SPOTIFY_TOKEN_PATH = APP_DIR / "spotify_tokens.json"
DEVICE_PATH = APP_DIR / "device.json"
STATUSLINE_MARKER = APP_DIR / "statusline.json"
CONFIG_PATH = APP_DIR / "config.json"
CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CLAUDE_SKILLS_DIR = Path.home() / ".claude" / "skills"
DJ_SKILL_DIR = CLAUDE_SKILLS_DIR / "dj"
DJ_SKILL_PATH = DJ_SKILL_DIR / "SKILL.md"

# Only scopes the product actually uses. Missing any on a stored token
# forces re-login via ensure_session.
SPOTIFY_SCOPES = " ".join(
    [
        "user-read-playback-state",
        "user-modify-playback-state",
        "playlist-read-private",
        "playlist-read-collaborative",
        "user-top-read",
        "user-read-recently-played",
    ]
)
SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"


class ConfigError(RuntimeError):
    """Missing or invalid durable app configuration."""


def load_app_config() -> dict[str, Any]:
    """Return ~/.claude-dj/config.json contents, or {} if missing/invalid."""
    if not CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_app_config(data: dict[str, Any]) -> None:
    """Write config.json with mode 600."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    CONFIG_PATH.chmod(0o600)


def set_spotify_client_id(client_id: str) -> None:
    """Persist Spotify client id, merging into existing config."""
    data = load_app_config()
    data["spotify_client_id"] = client_id.strip()
    save_app_config(data)


def resolve_spotify_client_id() -> str:
    """Env SPOTIFY_CLIENT_ID if set, else config.json, else ConfigError."""
    env = (os.environ.get("SPOTIFY_CLIENT_ID") or "").strip()
    if env:
        return env
    file_id = str(load_app_config().get("spotify_client_id") or "").strip()
    if file_id:
        return file_id
    raise ConfigError(
        "Spotify client ID not configured; run: dj setup"
    )
