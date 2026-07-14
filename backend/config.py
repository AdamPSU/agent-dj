import os
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8787
BASE_URL = f"http://{HOST}:{PORT}"

APP_DIR = Path.home() / ".claude-dj"
SPOTIFY_TOKEN_PATH = APP_DIR / "spotify_tokens.json"
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_SCOPES = " ".join(
    [
        "playlist-read-private",
        "playlist-read-collaborative",
        "user-read-recently-played",
        "user-read-playback-state",
        "user-modify-playback-state",
    ]
)
SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
