"""Spotify adapter for Claude DJ.

This module will own Spotify auth, playback state, playlist reads, and playback actions.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
import base64
import hashlib
import json
import secrets
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
LOGIN_COMPLETE_HTML = b"Spotify login complete. You can close this tab."


class SpotifyAuthError(RuntimeError):
    """Raised when Spotify OAuth cannot complete."""


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


def save_token(token_file: Path, token: dict[str, object]) -> None:
    """Persist a Spotify token cache with user-only file permissions."""
    token_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    token_file.write_text(json.dumps(token, indent=2), encoding="utf-8")
    token_file.chmod(0o600)
