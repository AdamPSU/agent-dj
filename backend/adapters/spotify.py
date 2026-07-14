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


def get_access_token() -> str:
    """Return a valid Spotify access token, renewing it first if it has expired."""
    tokens = load_tokens()
    if tokens is None:
        raise SystemExit("not logged in; run: claude-dj spotify-login")
    if time.time() >= float(tokens["expires_at"]):
        tokens = refresh_tokens(tokens["refresh_token"])
        save_tokens(tokens)
    return tokens["access_token"]


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
