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
    SPOTIFY_API_BASE,
    SPOTIFY_AUTHORIZE_URL,
    SPOTIFY_SCOPES,
    SPOTIFY_TOKEN_PATH,
    SPOTIFY_TOKEN_URL,
    ConfigError,
    resolve_spotify_client_id,
)

# Optional test override.
SPOTIFY_CLIENT_ID = ""


def _client_id() -> str:
    if SPOTIFY_CLIENT_ID:
        return SPOTIFY_CLIENT_ID
    return resolve_spotify_client_id()


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def authorize_url(state: str, challenge: str, redirect_uri: str) -> str:
    try:
        client_id = _client_id()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc
    if not client_id:
        raise SystemExit("Spotify client ID not configured; run: dj auth")
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
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
    payload = _post_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": _client_id(),
            "code_verifier": verifier,
        }
    )
    return _normalize_tokens(payload)


def refresh_tokens(refresh_token: str) -> dict:
    payload = _post_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": _client_id(),
        }
    )
    if "refresh_token" not in payload:
        payload["refresh_token"] = refresh_token
    return _normalize_tokens(payload)


def _normalize_tokens(payload: dict) -> dict:
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
    payload = json.dumps(tokens) + "\n"
    tmp = SPOTIFY_TOKEN_PATH.with_suffix(SPOTIFY_TOKEN_PATH.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(SPOTIFY_TOKEN_PATH)


def load_tokens() -> dict | None:
    if not SPOTIFY_TOKEN_PATH.exists():
        return None
    raw = SPOTIFY_TOKEN_PATH.read_text(encoding="utf-8")
    if not raw.strip():
        return None
    data, end = json.JSONDecoder().raw_decode(raw)
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid Spotify token file: {SPOTIFY_TOKEN_PATH}")
    # Repair trailing junk (e.g. an extra '}') so statusline ticks don't crash.
    if raw[end:].strip():
        save_tokens(data)
    return data


def clear_tokens() -> None:
    if SPOTIFY_TOKEN_PATH.exists():
        try:
            SPOTIFY_TOKEN_PATH.unlink()
        except OSError:
            pass


def get_access_token() -> str:
    tokens = load_tokens()
    if tokens is None:
        raise RuntimeError("not logged in; run: dj auth")
    if time.time() >= float(tokens["expires_at"]):
        try:
            _client_id()
        except ConfigError as exc:
            raise RuntimeError(str(exc)) from exc
        try:
            tokens = refresh_tokens(tokens["refresh_token"])
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise RuntimeError(f"Spotify token refresh failed ({exc.code}): {body}") from exc
        save_tokens(tokens)
    return tokens["access_token"]


def required_scopes() -> frozenset[str]:
    return frozenset(SPOTIFY_SCOPES.split())


def token_has_required_scopes(tokens: dict | None = None) -> bool:
    tokens = tokens if tokens is not None else load_tokens()
    if not tokens:
        return False
    granted = frozenset((tokens.get("scope") or "").split())
    return required_scopes().issubset(granted)


def get_me() -> dict:
    token = get_access_token()
    req = urllib.request.Request(
        f"{SPOTIFY_API_BASE}/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"Spotify API {exc.code}: {body}") from exc


def session_is_valid() -> bool:
    if not token_has_required_scopes():
        return False
    try:
        get_me()
        return True
    except Exception:
        return False


def ensure_session() -> None:
    if session_is_valid():
        return
    clear_tokens()
    login()


def get_now_playing() -> dict | None:
    """Return current track snapshot, or None if nothing / non-track."""
    token = get_access_token()
    url = f"{SPOTIFY_API_BASE}/me/player"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 204:
                return None
            raw = resp.read()
            if not raw:
                return None
            data = json.loads(raw.decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 204:
            return None
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"Spotify API {exc.code}: {body}") from exc

    item = data.get("item")
    if not isinstance(item, dict) or item.get("type") != "track" or not item.get("id"):
        return None
    artists = ", ".join(
        a.get("name") or "" for a in (item.get("artists") or []) if a.get("name")
    )
    progress = data.get("progress_ms")
    duration = item.get("duration_ms")
    return {
        "spotify_id": item["id"],
        "name": item.get("name") or "",
        "artists": artists,
        "progress_ms": int(progress) if progress is not None else 0,
        "duration_ms": int(duration) if duration is not None else 0,
        "is_playing": bool(data.get("is_playing")),
    }


def login() -> dict:
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
