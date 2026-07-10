"""Application settings for Claude DJ.

This module owns environment variables, local paths, and config loading.
"""

from dataclasses import dataclass
from pathlib import Path
import os


APP_HOME_ENV = "CLAUDE_DJ_HOME"
APP_DIR_NAME = ".claude-dj"
RUNTIME_FILE_NAME = "runtime.json"
DATABASE_FILE_NAME = "claude-dj.sqlite3"
SPOTIFY_TOKEN_FILE_NAME = "spotify-token.json"
SPOTIFY_DEVICE_FILE_NAME = "spotify-device.json"
NARRATION_DIR_NAME = "narration"
ENV_FILE_NAME = ".env"
DEFAULT_SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8888/callback"
LOCAL_MUQ_MODEL_NAME = "OpenMuQ/MuQ-large-msd-iter"
LOCAL_MUQ_DIMENSIONS = 1024
DEFAULT_ELEVENLABS_MODEL_ID = "eleven_v3"
DEFAULT_ELEVENLABS_OUTPUT_FORMAT = "mp3_44100_128"
PACKAGE_ENV_FILE = Path(__file__).with_name(ENV_FILE_NAME)


class MissingConfigError(RuntimeError):
    """Raised when required local app configuration is missing."""


@dataclass(frozen=True)
class SpotifyConfig:
    """Spotify OAuth settings for the installed-app PKCE flow."""

    client_id: str
    redirect_uri: str


@dataclass(frozen=True)
class EmbeddingConfig:
    """Local MuQ model metadata."""

    model_name: str
    model_version: str | None
    dimensions: int


@dataclass(frozen=True)
class NarrationConfig:
    """ElevenLabs settings for local DJ narration."""

    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    elevenlabs_model_id: str
    elevenlabs_output_format: str
    elevenlabs_optimize_streaming_latency: int | None = None


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


def get_spotify_device_file(app_dir: Path | None = None) -> Path:
    """Return the local preferred Spotify device path."""
    return (app_dir or get_app_dir()) / SPOTIFY_DEVICE_FILE_NAME


def get_narration_dir(app_dir: Path | None = None) -> Path:
    """Return the local temp directory for generated narration audio."""
    return (app_dir or get_app_dir()) / NARRATION_DIR_NAME


def ensure_narration_dir(app_dir: Path | None = None) -> Path:
    """Create and return the local narration audio directory."""
    path = get_narration_dir(app_dir)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def get_spotify_config() -> SpotifyConfig:
    """Return Spotify PKCE OAuth settings from the environment."""
    _load_local_env()
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    if not client_id:
        raise MissingConfigError("SPOTIFY_CLIENT_ID is required for Spotify login.")

    return SpotifyConfig(
        client_id=client_id,
        redirect_uri=os.environ.get("SPOTIFY_REDIRECT_URI", DEFAULT_SPOTIFY_REDIRECT_URI),
    )


def get_embedding_config() -> EmbeddingConfig:
    """Return the local MuQ audio embedding model."""
    return EmbeddingConfig(
        model_name=LOCAL_MUQ_MODEL_NAME,
        model_version=None,
        dimensions=LOCAL_MUQ_DIMENSIONS,
    )


def get_narration_config() -> NarrationConfig | None:
    """Return ElevenLabs narration settings, or None when narration is disabled."""
    _load_local_env()
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID")
    if not api_key or not voice_id:
        return None

    latency = os.environ.get("ELEVENLABS_OPTIMIZE_STREAMING_LATENCY")
    return NarrationConfig(
        elevenlabs_api_key=api_key,
        elevenlabs_voice_id=voice_id,
        elevenlabs_model_id=os.environ.get("ELEVENLABS_MODEL_ID", DEFAULT_ELEVENLABS_MODEL_ID),
        elevenlabs_output_format=os.environ.get("ELEVENLABS_OUTPUT_FORMAT", DEFAULT_ELEVENLABS_OUTPUT_FORMAT),
        elevenlabs_optimize_streaming_latency=int(latency) if latency else None,
    )


def _load_local_env() -> None:
    for env_file in _env_file_candidates():
        _load_env_file(env_file)


def _env_file_candidates() -> tuple[Path, ...]:
    override = os.environ.get("CLAUDE_DJ_ENV_FILE")
    candidates = []
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(get_app_dir() / ENV_FILE_NAME)
    candidates.append(PACKAGE_ENV_FILE)
    return tuple(candidates)


def _load_env_file(env_file: Path) -> None:
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, _strip_env_value(value.strip()))


def _strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
