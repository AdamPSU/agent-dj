"""Spotify adapter for Claude DJ.

This module will own Spotify auth, playback state, playlist reads, and playback actions.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
import base64
import hashlib
import json
import secrets
import urllib.error
import urllib.request
import webbrowser

from claude_dj.config import SpotifyConfig


DEFAULT_SPOTIFY_SCOPES = (
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
)
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE_URL = "https://api.spotify.com/v1"
LOGIN_COMPLETE_HTML = b"Spotify login complete. You can close this tab."


class SpotifyAuthError(RuntimeError):
    """Raised when Spotify OAuth cannot complete."""


class SpotifyAPIAuthError(RuntimeError):
    """Raised when Spotify rejects the current access token."""


class SpotifyAPIForbiddenError(RuntimeError):
    """Raised when Spotify denies access to a requested API resource."""


@dataclass(frozen=True)
class SpotifyPlaylist:
    """Normalized Spotify playlist metadata."""

    id: str
    name: str
    description: str | None


@dataclass(frozen=True)
class SpotifyTrack:
    """Normalized Spotify track metadata used by the local catalog."""

    spotify_track_id: str
    spotify_uri: str
    isrc: str | None
    title: str
    artist_name: str
    album_name: str | None
    duration_ms: int | None
    explicit: bool
    popularity: int | None


@dataclass(frozen=True)
class SpotifyPlaylistTrack:
    """A normalized track with its playlist membership metadata."""

    track: SpotifyTrack
    position: int
    added_at: str | None


def pkce_challenge(code_verifier: str) -> str:
    """Return the Spotify PKCE S256 challenge for a code verifier."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def build_authorize_url(
    config: SpotifyConfig,
    code_verifier: str,
    state: str,
    scopes: tuple[str, ...] = DEFAULT_SPOTIFY_SCOPES,
) -> str:
    """Build the browser URL for Spotify Authorization Code with PKCE."""
    query = urlencode(
        {
            "client_id": config.client_id,
            "response_type": "code",
            "redirect_uri": config.redirect_uri,
            "scope": " ".join(scopes),
            "code_challenge_method": "S256",
            "code_challenge": pkce_challenge(code_verifier),
            "state": state,
        }
    )
    return f"https://accounts.spotify.com/authorize?{query}"


def perform_spotify_login(config: SpotifyConfig, token_file: Path) -> dict[str, object]:
    """Run browser-based Spotify PKCE login and save the resulting token."""
    code_verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(24)
    auth_url = build_authorize_url(config=config, code_verifier=code_verifier, state=state)

    code = wait_for_authorization_code(config.redirect_uri, expected_state=state, open_url=auth_url)
    token = exchange_authorization_code(
        config=config,
        code=code,
        code_verifier=code_verifier,
    )
    save_token(token_file, token)
    return token


def wait_for_authorization_code(
    redirect_uri: str,
    expected_state: str,
    open_url: str,
) -> str:
    """Open Spotify login and wait for the local callback authorization code."""
    parsed = urlparse(redirect_uri)
    if parsed.hostname != "127.0.0.1" or parsed.port is None:
        raise SpotifyAuthError("Spotify redirect URI must use http://127.0.0.1:<port>/callback.")

    callback_path = parsed.path or "/"

    class CallbackHandler(BaseHTTPRequestHandler):
        server: HTTPServer

        def do_GET(self) -> None:
            request = urlparse(self.path)
            params = parse_qs(request.query)
            if request.path != callback_path:
                self.send_error(404)
                return

            if "error" in params:
                self.server.auth_error = params["error"][0]
            elif params.get("state", [None])[0] != expected_state:
                self.server.auth_error = "Spotify login returned an invalid state."
            elif "code" not in params:
                self.server.auth_error = "Spotify login did not return an authorization code."
            else:
                self.server.auth_code = params["code"][0]

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(LOGIN_COMPLETE_HTML)))
            self.end_headers()
            self.wfile.write(LOGIN_COMPLETE_HTML)

        def log_message(self, format: str, *args: object) -> None:
            """Silence callback server request logging."""

    server = HTTPServer(("127.0.0.1", parsed.port), CallbackHandler)
    server.auth_code = None
    server.auth_error = None

    try:
        webbrowser.open(open_url)
        while server.auth_code is None and server.auth_error is None:
            server.handle_request()
    finally:
        server.server_close()

    if server.auth_error is not None:
        raise SpotifyAuthError(str(server.auth_error))
    return str(server.auth_code)


def exchange_authorization_code(
    config: SpotifyConfig,
    code: str,
    code_verifier: str,
    urlopen=urllib.request.urlopen,
) -> dict[str, object]:
    """Exchange a Spotify authorization code for access and refresh tokens."""
    request = urllib.request.Request(
        TOKEN_URL,
        data=urlencode(
            {
                "client_id": config.client_id,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.redirect_uri,
                "code_verifier": code_verifier,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def load_token(token_file: Path) -> dict[str, object]:
    """Load the local Spotify token cache."""
    try:
        token = json.loads(token_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SpotifyAuthError("Spotify login is required before playlist indexing.") from exc
    except json.JSONDecodeError as exc:
        raise SpotifyAuthError("Spotify token cache is invalid. Run spotify-login again.") from exc

    if not isinstance(token, dict) or not isinstance(token.get("access_token"), str):
        raise SpotifyAuthError("Spotify token cache is invalid. Run spotify-login again.")
    return token


def refresh_access_token(
    config: SpotifyConfig,
    token_file: Path,
    token: dict[str, object],
    urlopen=urllib.request.urlopen,
) -> dict[str, object]:
    """Refresh a Spotify access token for the public PKCE client."""
    refresh_token = token.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise SpotifyAuthError("Spotify login expired. Run spotify-login again.")

    request = urllib.request.Request(
        TOKEN_URL,
        data=urlencode(
            {
                "client_id": config.client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        refreshed = json.loads(response.read().decode("utf-8"))

    if "refresh_token" not in refreshed:
        refreshed["refresh_token"] = refresh_token
    save_token(token_file, refreshed)
    return refreshed


def fetch_all_playlists(
    access_token: str,
    urlopen=urllib.request.urlopen,
) -> list[SpotifyPlaylist]:
    """Fetch all playlists visible to the current Spotify user."""
    items = _fetch_paginated(
        f"{API_BASE_URL}/me/playlists?limit=50",
        access_token=access_token,
        urlopen=urlopen,
    )
    playlists: list[SpotifyPlaylist] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        playlist_id = item.get("id")
        name = item.get("name")
        if isinstance(playlist_id, str) and isinstance(name, str):
            description = item.get("description")
            playlists.append(
                SpotifyPlaylist(
                    id=playlist_id,
                    name=name,
                    description=description if isinstance(description, str) else None,
                )
            )
    return playlists


def fetch_playlist_tracks(
    access_token: str,
    playlist_id: str,
    urlopen=urllib.request.urlopen,
) -> list[SpotifyPlaylistTrack]:
    """Fetch and normalize playable track items from a Spotify playlist."""
    tracks, _skipped_count = fetch_playlist_tracks_with_skipped_count(
        access_token,
        playlist_id,
        urlopen=urlopen,
    )
    return tracks


def fetch_playlist_tracks_with_skipped_count(
    access_token: str,
    playlist_id: str,
    urlopen=urllib.request.urlopen,
) -> tuple[list[SpotifyPlaylistTrack], int]:
    """Fetch playlist tracks and count local files, episodes, and malformed rows skipped."""
    items = _fetch_paginated(
        f"{API_BASE_URL}/playlists/{playlist_id}/items?limit=100&offset=0",
        access_token=access_token,
        urlopen=urlopen,
    )
    tracks: list[SpotifyPlaylistTrack] = []
    skipped_count = 0
    for position, item in enumerate(items):
        normalized = _normalize_playlist_track(item, position)
        if normalized is None:
            skipped_count += 1
        else:
            tracks.append(normalized)
    return tracks, skipped_count


def save_token(token_file: Path, token: dict[str, object]) -> None:
    """Persist a Spotify token cache with user-only file permissions."""
    token_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    token_file.write_text(json.dumps(token, indent=2), encoding="utf-8")
    token_file.chmod(0o600)


def _fetch_paginated(
    url: str,
    *,
    access_token: str,
    urlopen,
) -> list[object]:
    items: list[object] = []
    next_url: str | None = url
    while next_url is not None:
        page = _get_json(next_url, access_token=access_token, urlopen=urlopen)
        page_items = page.get("items", [])
        if isinstance(page_items, list):
            items.extend(page_items)
        next_value = page.get("next")
        next_url = next_value if isinstance(next_value, str) and next_value else None
    return items


def _get_json(url: str, *, access_token: str, urlopen) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise SpotifyAPIAuthError("Spotify access token is expired or invalid.") from exc
        if exc.code == 403:
            raise SpotifyAPIForbiddenError("Spotify denied access to the requested resource.") from exc
        raise

    return data if isinstance(data, dict) else {}


def _normalize_playlist_track(item: object, position: int) -> SpotifyPlaylistTrack | None:
    if not isinstance(item, dict) or item.get("is_local") is True:
        return None

    track = item.get("item") if "item" in item else item.get("track")
    if not isinstance(track, dict) or track.get("type") != "track":
        return None

    spotify_track_id = track.get("id")
    spotify_uri = track.get("uri")
    title = track.get("name")
    if not all(isinstance(value, str) and value for value in (spotify_track_id, spotify_uri, title)):
        return None

    artist_names = [
        artist.get("name")
        for artist in track.get("artists", [])
        if isinstance(artist, dict) and isinstance(artist.get("name"), str)
    ]
    artist_name = ", ".join(artist_names) if artist_names else "Unknown Artist"
    album = track.get("album")
    album_name = album.get("name") if isinstance(album, dict) and isinstance(album.get("name"), str) else None
    external_ids = track.get("external_ids")
    isrc = (
        external_ids.get("isrc")
        if isinstance(external_ids, dict) and isinstance(external_ids.get("isrc"), str)
        else None
    )
    duration_ms = track.get("duration_ms")
    popularity = track.get("popularity")
    added_at = item.get("added_at")

    return SpotifyPlaylistTrack(
        track=SpotifyTrack(
            spotify_track_id=str(spotify_track_id),
            spotify_uri=str(spotify_uri),
            isrc=isrc,
            title=str(title),
            artist_name=artist_name,
            album_name=album_name,
            duration_ms=duration_ms if isinstance(duration_ms, int) else None,
            explicit=bool(track.get("explicit", False)),
            popularity=popularity if isinstance(popularity, int) else None,
        ),
        position=position,
        added_at=added_at if isinstance(added_at, str) else None,
    )
