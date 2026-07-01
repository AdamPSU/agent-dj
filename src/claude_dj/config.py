"""Application settings for Claude DJ.

This module will own environment variables, local paths, and config loading.
"""

from dataclasses import dataclass
from pathlib import Path
import os


APP_HOME_ENV = "CLAUDE_DJ_HOME"
APP_DIR_NAME = ".claude-dj"
RUNTIME_FILE_NAME = "runtime.json"
DATABASE_FILE_NAME = "claude-dj.sqlite3"
SPOTIFY_TOKEN_FILE_NAME = "spotify-token.json"
DEFAULT_SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8888/callback"


class MissingConfigError(RuntimeError):
    """Raised when required local app configuration is missing."""


@dataclass(frozen=True)
class SpotifyConfig:
    """Spotify OAuth settings for the installed-app PKCE flow."""

    client_id: str
    redirect_uri: str


def get_app_dir() -> Path:
    """Return the local Claude DJ app directory."""
    override = os.environ.get(APP_HOME_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / APP_DIR_NAME


def ensure_app_dir(app_dir: Path | None = None) -> Path:
    """Create and return the local Claude DJ app directory."""
    resolved = app_dir or get_app_dir()
    resolved.mkdir(mode=0o700, parents=True, exist_ok=True)
    return resolved


def get_runtime_file(app_dir: Path | None = None) -> Path:
    """Return the runtime file path used to find the local daemon."""
    return (app_dir or get_app_dir()) / RUNTIME_FILE_NAME


def get_database_file(app_dir: Path | None = None) -> Path:
    """Return the local SQLite database path for durable Claude DJ data."""
    return (app_dir or get_app_dir()) / DATABASE_FILE_NAME


def get_spotify_token_file(app_dir: Path | None = None) -> Path:
    """Return the local Spotify OAuth token cache path."""
    return (app_dir or get_app_dir()) / SPOTIFY_TOKEN_FILE_NAME


def get_spotify_config() -> SpotifyConfig:
    """Return Spotify PKCE OAuth settings from the environment."""
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    if not client_id:
        raise MissingConfigError("SPOTIFY_CLIENT_ID is required for Spotify login.")

    return SpotifyConfig(
        client_id=client_id,
        redirect_uri=os.environ.get("SPOTIFY_REDIRECT_URI", DEFAULT_SPOTIFY_REDIRECT_URI),
    )
