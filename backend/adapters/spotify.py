import base64
import hashlib
import json
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from backend.config import (
    APP_DIR,
    DEVICE_PATH,
    SPOTIFY_API_BASE,
    SPOTIFY_AUTHORIZE_URL,
    SPOTIFY_CLIENT_ID,
    SPOTIFY_SCOPES,
    SPOTIFY_TOKEN_PATH,
    SPOTIFY_TOKEN_URL,
)


def pkce_pair() -> tuple[str, str]:
    """Build a one-time secret pair so login cannot be faked by someone intercepting the redirect."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def free_port() -> int:
    """Pick an unused local port for the brief Spotify login callback."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def authorize_url(state: str, challenge: str, redirect_uri: str) -> str:
    """Build the Spotify consent page URL the user opens in their browser."""
    if not SPOTIFY_CLIENT_ID:
        raise SystemExit("SPOTIFY_CLIENT_ID is not set")
    query = urllib.parse.urlencode(
        {
            "client_id": SPOTIFY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": SPOTIFY_SCOPES,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
    )
    return f"{SPOTIFY_AUTHORIZE_URL}?{query}"


def _post_token(body: dict) -> dict:
    """Ask Spotify to issue or renew login tokens."""
    data = urllib.parse.urlencode(body).encode()
    req = urllib.request.Request(
        SPOTIFY_TOKEN_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def exchange_code(code: str, verifier: str, redirect_uri: str) -> dict:
    """Turn the one-time browser approval code into saved access credentials."""
    payload = _post_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": SPOTIFY_CLIENT_ID,
            "code_verifier": verifier,
        }
    )
    return _normalize_tokens(payload)


def refresh_tokens(refresh_token: str) -> dict:
    """Get a new short-lived access token without asking the user to log in again."""
    payload = _post_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": SPOTIFY_CLIENT_ID,
        }
    )
    if "refresh_token" not in payload:
        payload["refresh_token"] = refresh_token
    return _normalize_tokens(payload)


def _normalize_tokens(payload: dict) -> dict:
    """Shape Spotify's token reply into the fields we store on disk."""
    expires_in = int(payload.get("expires_in", 3600))
    return {
        "access_token": payload["access_token"],
        "refresh_token": payload["refresh_token"],
        "expires_at": time.time() + expires_in - 30,
        "scope": payload.get("scope", SPOTIFY_SCOPES),
        "token_type": payload.get("token_type", "Bearer"),
    }


def save_tokens(tokens: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SPOTIFY_TOKEN_PATH.write_text(json.dumps(tokens), encoding="utf-8")
    SPOTIFY_TOKEN_PATH.chmod(0o600)


def load_tokens() -> dict | None:
    if not SPOTIFY_TOKEN_PATH.exists():
        return None
    return json.loads(SPOTIFY_TOKEN_PATH.read_text(encoding="utf-8"))


def tokens_missing() -> bool:
    return not SPOTIFY_TOKEN_PATH.exists()


def clear_tokens() -> None:
    """Forget saved Spotify credentials so the next login starts clean."""
    if SPOTIFY_TOKEN_PATH.exists():
        SPOTIFY_TOKEN_PATH.unlink()


def get_access_token() -> str:
    """Return a valid Spotify access token, renewing it first if it has expired."""
    tokens = load_tokens()
    if tokens is None:
        raise RuntimeError("not logged in; run: claude-dj play")
    if time.time() >= float(tokens["expires_at"]):
        if not SPOTIFY_CLIENT_ID:
            raise RuntimeError(
                "Spotify session expired and SPOTIFY_CLIENT_ID is not set; "
                "export SPOTIFY_CLIENT_ID and run: claude-dj play"
            )
        try:
            tokens = refresh_tokens(tokens["refresh_token"])
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise RuntimeError(f"Spotify token refresh failed ({exc.code}): {body}") from exc
        save_tokens(tokens)
    return tokens["access_token"]


def session_is_valid() -> bool:
    """True when we can refresh if needed and Spotify accepts the access token."""
    try:
        get_me()
        return True
    except Exception:
        return False


def ensure_session() -> None:
    """Make sure Spotify auth works: refresh if possible, otherwise open browser login."""
    if session_is_valid():
        return
    # Stale/invalid tokens block a clean re-login.
    clear_tokens()
    login()


def api_get(path: str, params: dict | None = None) -> dict:
    """Call the Spotify Web API with the saved user token."""
    token = get_access_token()
    if path.startswith("http"):
        url = path
    else:
        url = f"{SPOTIFY_API_BASE}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"Spotify API {exc.code}: {body}") from exc


def get_me() -> dict:
    """Return the signed-in Spotify user profile."""
    return api_get("/me")


def api_put(path: str, body: dict | None = None, params: dict | None = None) -> None:
    """PUT to the Spotify Web API (playback commands). Empty 204 is success."""
    token = get_access_token()
    if path.startswith("http"):
        url = path
    else:
        url = f"{SPOTIFY_API_BASE}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
    data = None if body is None else json.dumps(body).encode()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=data, method="PUT", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode(errors="replace")
        raise RuntimeError(f"Spotify API {exc.code}: {err_body}") from exc


def get_playback_state() -> dict | None:
    """Return raw /me/player JSON, or None if 204 no content."""
    token = get_access_token()
    url = f"{SPOTIFY_API_BASE}/me/player"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 204:
                return None
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw.decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 204:
            return None
        err_body = exc.read().decode(errors="replace")
        raise RuntimeError(f"Spotify API {exc.code}: {err_body}") from exc


def start_playback_uris(uris: list[str], *, device_id: str | None = None) -> None:
    """Start playing specific track URIs on the active (or given) device."""
    params = {"device_id": device_id} if device_id else None
    api_put("/me/player/play", body={"uris": uris}, params=params)


def set_shuffle(state: bool, *, device_id: str | None = None) -> None:
    params: dict = {"state": "true" if state else "false"}
    if device_id:
        params["device_id"] = device_id
    api_put("/me/player/shuffle", body=None, params=params)


def set_repeat(state: str, *, device_id: str | None = None) -> None:
    """state: off | track | context"""
    params: dict = {"state": state}
    if device_id:
        params["device_id"] = device_id
    api_put("/me/player/repeat", body=None, params=params)


def list_devices() -> list[dict]:
    """Return available Spotify Connect devices (simplified rows)."""
    data = api_get("/me/player/devices")
    rows = []
    for d in data.get("devices") or []:
        rows.append(
            {
                "id": d.get("id"),
                "name": d.get("name") or "",
                "type": d.get("type") or "",
                "is_active": bool(d.get("is_active")),
                "is_restricted": bool(d.get("is_restricted")),
                "volume_percent": d.get("volume_percent"),
            }
        )
    return rows


def transfer_playback(device_id: str, *, play: bool = False) -> None:
    """Make device the active Connect target (optionally start/resume play)."""
    api_put("/me/player", body={"device_ids": [device_id], "play": play})


def load_preferred_device_id() -> str | None:
    if not DEVICE_PATH.exists():
        return None
    try:
        data = json.loads(DEVICE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    device_id = data.get("device_id")
    return str(device_id) if device_id else None


def save_preferred_device_id(device_id: str) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    DEVICE_PATH.write_text(json.dumps({"device_id": device_id}), encoding="utf-8")
    DEVICE_PATH.chmod(0o600)


def clear_preferred_device_id() -> None:
    if DEVICE_PATH.exists():
        DEVICE_PATH.unlink()


def _iter_pages(path: str, params: dict | None = None):
    """Walk a paginated Spotify list endpoint."""
    query = dict(params or {})
    query.setdefault("limit", 50)
    data = api_get(path, query)
    while True:
        for item in data.get("items") or []:
            yield item
        next_url = data.get("next")
        if not next_url:
            break
        data = api_get(next_url)


def iter_top_tracks(time_range: str = "short_term", *, limit: int = 50):
    """Yield simplified top-track rows (affinity list) in rank order."""
    if time_range not in {"short_term", "medium_term", "long_term"}:
        raise ValueError(f"invalid time_range: {time_range}")
    capped = max(1, min(int(limit), 50))
    data = api_get(
        "/me/top/tracks",
        {"time_range": time_range, "limit": capped},
    )
    for track in data.get("items") or []:
        if not isinstance(track, dict) or not track.get("id"):
            continue
        artists = ", ".join(
            a.get("name") or "" for a in (track.get("artists") or []) if a.get("name")
        )
        yield {
            "spotify_id": track["id"],
            "name": track.get("name") or "",
            "artists": artists,
        }


def iter_owned_playlists():
    """Yield playlists owned by the signed-in user (not merely followed)."""
    me_id = get_me()["id"]
    for playlist in _iter_pages("/me/playlists"):
        owner_id = (playlist.get("owner") or {}).get("id")
        if owner_id == me_id:
            yield playlist


def iter_playlist_tracks(playlist_id: str):
    """Yield simplified track rows from one playlist, skipping locals/episodes/missing."""
    for row in _iter_pages(f"/playlists/{playlist_id}/items"):
        if row.get("is_local"):
            continue
        # Spotify returns the media under "item" (newer) or "track" (legacy).
        track = row.get("item") or row.get("track")
        if not isinstance(track, dict):
            continue
        if track.get("is_local"):
            continue
        if track.get("type") != "track" or not track.get("id"):
            continue
        artists = ", ".join(
            a.get("name") or "" for a in (track.get("artists") or []) if a.get("name")
        )
        album = track.get("album") or {}
        external_ids = track.get("external_ids") or {}
        yield {
            "spotify_id": track["id"],
            "name": track.get("name") or "",
            "artists": artists,
            "album_name": album.get("name"),
            "duration_ms": track.get("duration_ms"),
            "isrc": external_ids.get("isrc"),
            "added_at": row.get("added_at"),
        }


def login() -> dict:
    """Open the browser for Spotify consent, then save tokens for later API calls."""
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    port = free_port()
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            query = urllib.parse.parse_qs(parsed.query)
            if query.get("state", [None])[0] != state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"state mismatch")
                return
            if "error" in query:
                result["error"] = query["error"][0]
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"authorization failed")
                return
            result["code"] = query.get("code", [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Spotify login complete. You can close this tab.")

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    webbrowser.open(authorize_url(state, challenge, redirect_uri))
    thread.join(timeout=180)
    server.server_close()

    if "error" in result:
        raise SystemExit(f"Spotify authorization failed: {result['error']}")
    if not result.get("code"):
        raise SystemExit("Spotify login timed out or was cancelled")

    tokens = exchange_code(result["code"], verifier, redirect_uri)
    save_tokens(tokens)
    return {"ok": True, "path": str(SPOTIFY_TOKEN_PATH)}
