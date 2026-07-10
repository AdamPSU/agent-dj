"""Spotify adapter for Claude DJ.

This module owns Spotify auth, playback state, playlist reads, and playback actions.
"""

from collections.abc import Callable, Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar
from urllib.parse import parse_qs, urlencode, urlparse
import base64
import hashlib
import json
import secrets
import urllib.error
import urllib.request
import webbrowser

from claude_dj.config import MissingConfigError, SpotifyConfig, get_spotify_config


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
REQUEST_TIMEOUT_SECONDS = 10
T = TypeVar("T")


class SpotifyAuthError(RuntimeError):
    """Raised when Spotify OAuth cannot complete."""


class SpotifyAPIAuthError(RuntimeError):
    """Raised when Spotify rejects the current access token."""


class SpotifyAPIForbiddenError(RuntimeError):
    """Raised when Spotify denies access to a requested API resource."""


class SpotifyPlaybackError(RuntimeError):
    """Raised when Spotify cannot start playback."""


class SpotifyNoActiveDeviceError(SpotifyPlaybackError):
    """Raised when Spotify has no active device for playback."""


class SpotifyPlaybackForbiddenError(SpotifyPlaybackError):
    """Raised when Spotify denies playback control."""


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
class SpotifyDevice:
    """Spotify Connect device available to the current user."""

    id: str
    name: str
    type: str
    is_active: bool
    is_restricted: bool


@dataclass(frozen=True)
class SpotifyPlaybackState:
    """Current Spotify playback state needed by the DJ monitor."""

    item_uri: str | None
    is_playing: bool
    progress_ms: int | None = None
    duration_ms: int | None = None


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
    return _post_token_request(
        {
            "client_id": config.client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.redirect_uri,
            "code_verifier": code_verifier,
        },
        urlopen=urlopen,
    )


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

    refreshed = _post_token_request(
        {
            "client_id": config.client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        urlopen=urlopen,
    )

    if "refresh_token" not in refreshed:
        refreshed["refresh_token"] = refresh_token
    save_token(token_file, refreshed)
    return refreshed


def start_playback(
    access_token: str,
    spotify_uris: Sequence[str],
    *,
    device_id: str | None = None,
    urlopen=urllib.request.urlopen,
) -> None:
    """Interrupt current Spotify playback and start the provided track URIs."""
    if not spotify_uris:
        raise ValueError("At least one Spotify URI is required to start playback.")

    url = f"{API_BASE_URL}/me/player/play"
    if device_id:
        url = f"{url}?{urlencode({'device_id': device_id})}"
    request = urllib.request.Request(
        url,
        data=json.dumps({"uris": list(spotify_uris)}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="PUT",
    )
    _send_playback_request(request, urlopen=urlopen, generic_error="Spotify could not start playback.")


def start_playback_with_token(
    *,
    token_file: Path,
    spotify_uris: Sequence[str],
    device_id: str | None = None,
    config: SpotifyConfig | None = None,
    urlopen=urllib.request.urlopen,
) -> None:
    """Start Spotify playback using the saved token cache, refreshing once on 401."""
    _call_with_refreshed_token(
        token_file=token_file,
        config=config,
        urlopen=urlopen,
        missing_login_message="Spotify login is required before playback. Run /dj spotify-login.",
        call=lambda access_token: start_playback(
            access_token,
            spotify_uris,
            device_id=device_id,
            urlopen=urlopen,
        ),
    )


def fetch_available_devices(
    access_token: str,
    urlopen=urllib.request.urlopen,
) -> list[SpotifyDevice]:
    """Fetch Spotify Connect devices visible to the current user."""
    payload = _get_json(f"{API_BASE_URL}/me/player/devices", access_token=access_token, urlopen=urlopen)
    devices = payload.get("devices")
    if not isinstance(devices, list):
        return []

    normalized: list[SpotifyDevice] = []
    for item in devices:
        device = _normalize_device(item)
        if device is not None:
            normalized.append(device)
    return normalized


def fetch_available_devices_with_token(
    *,
    token_file: Path,
    config: SpotifyConfig | None = None,
    urlopen=urllib.request.urlopen,
) -> list[SpotifyDevice]:
    """Fetch available devices using the saved token cache, refreshing once on 401."""
    return _call_with_refreshed_token(
        token_file=token_file,
        config=config,
        urlopen=urlopen,
        missing_login_message="Spotify login is required before listing devices. Run /dj spotify-login.",
        call=lambda access_token: fetch_available_devices(access_token, urlopen=urlopen),
    )


def fetch_playback_state(
    access_token: str,
    urlopen=urllib.request.urlopen,
) -> SpotifyPlaybackState:
    """Fetch the current Spotify playback state."""
    request = urllib.request.Request(
        f"{API_BASE_URL}/me/player",
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if getattr(response, "status", None) == 204:
                return SpotifyPlaybackState(item_uri=None, is_playing=False)
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise SpotifyAPIAuthError("Spotify access token is expired or invalid.") from exc
        if exc.code == 403:
            raise SpotifyAPIForbiddenError("Spotify denied access to the requested resource.") from exc
        raise
    return _normalize_playback_state(data if isinstance(data, dict) else {})


def fetch_playback_state_with_token(
    *,
    token_file: Path,
    config: SpotifyConfig | None = None,
    urlopen=urllib.request.urlopen,
) -> SpotifyPlaybackState:
    """Fetch playback state using the saved token cache, refreshing once on 401."""
    return _call_with_refreshed_token(
        token_file=token_file,
        config=config,
        urlopen=urlopen,
        missing_login_message="Spotify login is required before reading playback state. Run /dj spotify-login.",
        call=lambda access_token: fetch_playback_state(access_token, urlopen=urlopen),
    )


def add_to_queue(
    access_token: str,
    spotify_uri: str,
    *,
    device_id: str | None = None,
    urlopen=urllib.request.urlopen,
) -> None:
    """Add one Spotify URI to the user's playback queue."""
    if not spotify_uri:
        raise ValueError("A Spotify URI is required to add to the queue.")

    query = {"uri": spotify_uri}
    if device_id:
        query["device_id"] = device_id
    request = urllib.request.Request(
        f"{API_BASE_URL}/me/player/queue?{urlencode(query)}",
        headers={"Authorization": f"Bearer {access_token}"},
        method="POST",
    )
    _send_playback_request(
        request,
        urlopen=urlopen,
        generic_error="Spotify could not add a track to the playback queue.",
    )


def add_to_queue_with_token(
    *,
    token_file: Path,
    spotify_uri: str,
    device_id: str | None = None,
    config: SpotifyConfig | None = None,
    urlopen=urllib.request.urlopen,
) -> None:
    """Add a URI to the playback queue using the saved token cache, refreshing once on 401."""
    _call_with_refreshed_token(
        token_file=token_file,
        config=config,
        urlopen=urlopen,
        missing_login_message="Spotify login is required before queueing playback. Run /dj spotify-login.",
        call=lambda access_token: add_to_queue(
            access_token,
            spotify_uri,
            device_id=device_id,
            urlopen=urlopen,
        ),
    )


def set_repeat_mode(
    access_token: str,
    state: str,
    *,
    device_id: str | None = None,
    urlopen=urllib.request.urlopen,
) -> None:
    """Set Spotify repeat mode for the current playback device."""
    if state not in {"track", "context", "off"}:
        raise ValueError("Spotify repeat mode must be 'track', 'context', or 'off'.")

    query = {"state": state}
    if device_id:
        query["device_id"] = device_id
    request = urllib.request.Request(
        f"{API_BASE_URL}/me/player/repeat?{urlencode(query)}",
        headers={"Authorization": f"Bearer {access_token}"},
        method="PUT",
    )
    _send_playback_request(
        request,
        urlopen=urlopen,
        generic_error="Spotify could not set repeat mode.",
    )


def set_repeat_mode_with_token(
    *,
    token_file: Path,
    state: str,
    device_id: str | None = None,
    config: SpotifyConfig | None = None,
    urlopen=urllib.request.urlopen,
) -> None:
    """Set repeat mode using the saved token cache, refreshing once on 401."""
    _call_with_refreshed_token(
        token_file=token_file,
        config=config,
        urlopen=urlopen,
        missing_login_message="Spotify login is required before setting repeat mode. Run /dj spotify-login.",
        call=lambda access_token: set_repeat_mode(
            access_token,
            state,
            device_id=device_id,
            urlopen=urlopen,
        ),
    )


def set_shuffle(
    access_token: str,
    enabled: bool,
    *,
    device_id: str | None = None,
    urlopen=urllib.request.urlopen,
) -> None:
    """Set Spotify shuffle state for the current playback device."""
    query = {"state": str(enabled).lower()}
    if device_id:
        query["device_id"] = device_id
    request = urllib.request.Request(
        f"{API_BASE_URL}/me/player/shuffle?{urlencode(query)}",
        headers={"Authorization": f"Bearer {access_token}"},
        method="PUT",
    )
    _send_playback_request(
        request,
        urlopen=urlopen,
        generic_error="Spotify could not set shuffle mode.",
    )


def set_shuffle_with_token(
    *,
    token_file: Path,
    enabled: bool,
    device_id: str | None = None,
    config: SpotifyConfig | None = None,
    urlopen=urllib.request.urlopen,
) -> None:
    """Set shuffle state using the saved token cache, refreshing once on 401."""
    _call_with_refreshed_token(
        token_file=token_file,
        config=config,
        urlopen=urlopen,
        missing_login_message="Spotify login is required before setting shuffle mode. Run /dj spotify-login.",
        call=lambda access_token: set_shuffle(
            access_token,
            enabled,
            device_id=device_id,
            urlopen=urlopen,
        ),
    )


def pause_playback(
    access_token: str,
    *,
    urlopen=urllib.request.urlopen,
) -> None:
    """Pause current Spotify playback."""
    request = urllib.request.Request(
        f"{API_BASE_URL}/me/player/pause",
        headers={"Authorization": f"Bearer {access_token}"},
        method="PUT",
    )
    _send_playback_request(request, urlopen=urlopen, generic_error="Spotify could not pause playback.")


def pause_playback_with_token(
    *,
    token_file: Path,
    config: SpotifyConfig | None = None,
    urlopen=urllib.request.urlopen,
) -> None:
    """Pause playback using the saved token cache, refreshing once on 401."""
    _call_with_refreshed_token(
        token_file=token_file,
        config=config,
        urlopen=urlopen,
        missing_login_message="Spotify login is required before pausing playback. Run /dj spotify-login.",
        call=lambda access_token: pause_playback(access_token, urlopen=urlopen),
    )


def resume_playback(
    access_token: str,
    *,
    urlopen=urllib.request.urlopen,
) -> None:
    """Resume current Spotify playback."""
    request = urllib.request.Request(
        f"{API_BASE_URL}/me/player/play",
        headers={"Authorization": f"Bearer {access_token}"},
        method="PUT",
    )
    _send_playback_request(request, urlopen=urlopen, generic_error="Spotify could not resume playback.")


def resume_playback_with_token(
    *,
    token_file: Path,
    config: SpotifyConfig | None = None,
    urlopen=urllib.request.urlopen,
) -> None:
    """Resume playback using the saved token cache, refreshing once on 401."""
    _call_with_refreshed_token(
        token_file=token_file,
        config=config,
        urlopen=urlopen,
        missing_login_message="Spotify login is required before resuming playback. Run /dj spotify-login.",
        call=lambda access_token: resume_playback(access_token, urlopen=urlopen),
    )


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


def _post_token_request(fields: dict[str, str], *, urlopen) -> dict[str, object]:
    request = urllib.request.Request(
        TOKEN_URL,
        data=urlencode(fields).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _call_with_refreshed_token(
    *,
    token_file: Path,
    config: SpotifyConfig | None,
    urlopen,
    missing_login_message: str,
    call: Callable[[str], T],
) -> T:
    try:
        token = load_token(token_file)
    except SpotifyAuthError as exc:
        raise SpotifyAuthError(missing_login_message) from exc

    try:
        return call(str(token["access_token"]))
    except SpotifyAPIAuthError:
        refreshed_token = _refresh_after_api_auth_error(
            config=config,
            token_file=token_file,
            token=token,
            urlopen=urlopen,
        )
        return call(str(refreshed_token["access_token"]))


def _refresh_after_api_auth_error(
    *,
    config: SpotifyConfig | None,
    token_file: Path,
    token: dict[str, object],
    urlopen,
) -> dict[str, object]:
    try:
        resolved_config = config or get_spotify_config()
    except MissingConfigError as exc:
        raise SpotifyAuthError("Spotify login expired. Run /dj spotify-login.") from exc
    return refresh_access_token(
        config=resolved_config,
        token_file=token_file,
        token=token,
        urlopen=urlopen,
    )


def _send_playback_request(request: urllib.request.Request, *, urlopen, generic_error: str) -> None:
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS):
            return
    except urllib.error.HTTPError as exc:
        _raise_playback_http_error(exc, generic_error=generic_error)


def _raise_playback_http_error(exc: urllib.error.HTTPError, *, generic_error: str) -> None:
    if exc.code == 401:
        raise SpotifyAPIAuthError("Spotify access token is expired or invalid.") from exc
    if exc.code == 403:
        raise SpotifyPlaybackForbiddenError("Spotify denied playback control.") from exc
    if exc.code == 404:
        raise SpotifyNoActiveDeviceError(
            "No active Spotify device found. Open Spotify on a device, then run /dj start again."
        ) from exc
    raise SpotifyPlaybackError(generic_error) from exc


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
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
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

    track = _playlist_track_payload(item)
    if track is None:
        return None

    required_strings = _required_track_strings(track)
    if required_strings is None:
        return None
    spotify_track_id, spotify_uri, title = required_strings

    duration_ms = track.get("duration_ms")
    popularity = track.get("popularity")
    added_at = item.get("added_at")

    return SpotifyPlaylistTrack(
        track=SpotifyTrack(
            spotify_track_id=str(spotify_track_id),
            spotify_uri=str(spotify_uri),
            isrc=_external_isrc(track),
            title=str(title),
            artist_name=_artist_name(track),
            album_name=_album_name(track),
            duration_ms=duration_ms if isinstance(duration_ms, int) else None,
            explicit=bool(track.get("explicit", False)),
            popularity=popularity if isinstance(popularity, int) else None,
        ),
        position=position,
        added_at=added_at if isinstance(added_at, str) else None,
    )


def _normalize_device(item: object) -> SpotifyDevice | None:
    if not isinstance(item, dict):
        return None

    device_id = item.get("id")
    name = item.get("name")
    device_type = item.get("type")
    if not all(isinstance(value, str) and value for value in (device_id, name, device_type)):
        return None

    return SpotifyDevice(
        id=str(device_id),
        name=str(name),
        type=str(device_type),
        is_active=bool(item.get("is_active", False)),
        is_restricted=bool(item.get("is_restricted", False)),
    )


def _normalize_playback_state(payload: dict[str, object]) -> SpotifyPlaybackState:
    item_uri = None
    duration_ms = None
    item = payload.get("item")
    if isinstance(item, dict) and item.get("type") == "track" and isinstance(item.get("uri"), str):
        item_uri = str(item["uri"])
        duration_value = item.get("duration_ms")
        duration_ms = duration_value if isinstance(duration_value, int) else None
    progress_value = payload.get("progress_ms")
    return SpotifyPlaybackState(
        item_uri=item_uri,
        is_playing=bool(payload.get("is_playing", False)),
        progress_ms=progress_value if isinstance(progress_value, int) else None,
        duration_ms=duration_ms,
    )


def _playlist_track_payload(item: dict[str, object]) -> dict[str, object] | None:
    track = item.get("item") if "item" in item else item.get("track")
    if not isinstance(track, dict) or track.get("type") != "track":
        return None
    return track


def _required_track_strings(track: dict[str, object]) -> tuple[str, str, str] | None:
    spotify_track_id = track.get("id")
    spotify_uri = track.get("uri")
    title = track.get("name")
    if not all(isinstance(value, str) and value for value in (spotify_track_id, spotify_uri, title)):
        return None
    return str(spotify_track_id), str(spotify_uri), str(title)


def _artist_name(track: dict[str, object]) -> str:
    artist_names = [
        artist.get("name")
        for artist in track.get("artists", [])
        if isinstance(artist, dict) and isinstance(artist.get("name"), str)
    ]
    return ", ".join(artist_names) if artist_names else "Unknown Artist"


def _album_name(track: dict[str, object]) -> str | None:
    album = track.get("album")
    if isinstance(album, dict) and isinstance(album.get("name"), str):
        return album.get("name")
    return None


def _external_isrc(track: dict[str, object]) -> str | None:
    external_ids = track.get("external_ids")
    if isinstance(external_ids, dict) and isinstance(external_ids.get("isrc"), str):
        return external_ids.get("isrc")
    return None
