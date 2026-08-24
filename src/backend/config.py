import json
import os
import re
from pathlib import Path
from typing import Any, Literal

APP_DIR = Path.home() / ".agent-dj"

SPOTIFY_TOKEN_PATH = APP_DIR / "spotify_tokens.json"
NOW_PLAYING_PATH = APP_DIR / "now_playing.json"
CONFIG_PATH = APP_DIR / "config.json"

SPOTIFY_SCOPES = "user-read-playback-state"
SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"

# artist, song, time
DEFAULT_PALETTE: tuple[str, str, str] = ("#888888", "#C1C1C1", "#486E6F")
_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

PiPlacement = Literal["above", "below"]
DEFAULT_PI_PLACEMENT: PiPlacement = "below"
_PI_PLACEMENTS = frozenset({"above", "below"})


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


def normalize_hex(value: str) -> str | None:
    raw = (value or "").strip()
    if not _HEX_RE.match(raw):
        return None
    body = raw[1:]
    if len(body) == 3:
        body = "".join(ch * 2 for ch in body)
    return f"#{body.upper()}"


def parse_palette(raw: Any) -> tuple[str, str, str]:
    """Resolve artist/song/time hex triple; invalid slots fall back to defaults."""
    defaults = list(DEFAULT_PALETTE)
    if not isinstance(raw, (list, tuple)):
        return (defaults[0], defaults[1], defaults[2])
    out = list(defaults)
    for i in range(min(3, len(raw))):
        normalized = normalize_hex(str(raw[i]))
        if normalized:
            out[i] = normalized
    return (out[0], out[1], out[2])


def load_palette() -> tuple[str, str, str]:
    return parse_palette(load_app_config().get("palette"))


def set_palette(colors: list[str] | tuple[str, ...]) -> tuple[str, str, str]:
    if len(colors) != 3:
        raise ConfigError("palette needs exactly 3 colors: artist song time")
    parsed: list[str] = []
    for i, c in enumerate(colors):
        n = normalize_hex(str(c))
        if not n:
            raise ConfigError(f"invalid hex color at position {i + 1}: {c!r}")
        parsed.append(n)
    triple = (parsed[0], parsed[1], parsed[2])
    data = load_app_config()
    data["palette"] = list(triple)
    save_app_config(data)
    return triple


def clear_palette() -> None:
    data = load_app_config()
    data.pop("palette", None)
    save_app_config(data)


def parse_pi_placement(raw: Any) -> PiPlacement:
    v = str(raw or "").strip().lower()
    if v in _PI_PLACEMENTS:
        return v  # type: ignore[return-value]
    return DEFAULT_PI_PLACEMENT


def load_pi_placement() -> PiPlacement:
    return parse_pi_placement(load_app_config().get("pi_placement"))


def set_pi_placement(value: str) -> PiPlacement:
    v = str(value or "").strip().lower()
    if v not in _PI_PLACEMENTS:
        raise ConfigError("placement must be above or below")
    data = load_app_config()
    data["pi_placement"] = v
    save_app_config(data)
    return v  # type: ignore[return-value]
