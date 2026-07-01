"""Spotify auth adapter tests."""

import json
from urllib.parse import parse_qs, urlparse

from claude_dj.adapters.spotify import (
    DEFAULT_SPOTIFY_SCOPES,
    build_authorize_url,
    exchange_authorization_code,
    pkce_challenge,
    save_token,
)
from claude_dj.config import SpotifyConfig


def test_pkce_challenge_uses_spotify_expected_s256_encoding() -> None:
    assert pkce_challenge("abc") == "ungWv48Bz-pBQUDeXa4iI7ADYaOWF3qctBD_YfIAFa0"


def test_build_authorize_url_uses_pkce_without_client_secret() -> None:
    config = SpotifyConfig(
        client_id="client-id",
        redirect_uri="http://127.0.0.1:8888/callback",
    )

    url = build_authorize_url(config=config, code_verifier="abc", state="state-value")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.spotify.com"
    assert parsed.path == "/authorize"
    assert query["client_id"] == ["client-id"]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8888/callback"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [pkce_challenge("abc")]
    assert query["state"] == ["state-value"]
    assert query["scope"] == [" ".join(DEFAULT_SPOTIFY_SCOPES)]
    assert "client_secret" not in query


def test_exchange_authorization_code_posts_pkce_token_request() -> None:
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps({"access_token": "access", "refresh_token": "refresh"}).encode(
                "utf-8"
            )

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    config = SpotifyConfig(
        client_id="client-id",
        redirect_uri="http://127.0.0.1:8888/callback",
    )

    token = exchange_authorization_code(
        config=config,
        code="auth-code",
        code_verifier="verifier",
        urlopen=fake_urlopen,
    )

    request, timeout = requests[0]
    body = parse_qs(request.data.decode("utf-8"))

    assert token["access_token"] == "access"
    assert token["refresh_token"] == "refresh"
    assert timeout == 10
    assert request.full_url == "https://accounts.spotify.com/api/token"
    assert request.get_method() == "POST"
    assert request.headers["Content-type"] == "application/x-www-form-urlencoded"
    assert body["client_id"] == ["client-id"]
    assert body["grant_type"] == ["authorization_code"]
    assert body["code"] == ["auth-code"]
    assert body["redirect_uri"] == ["http://127.0.0.1:8888/callback"]
    assert body["code_verifier"] == ["verifier"]
    assert "client_secret" not in body


def test_save_token_writes_user_only_token_file(tmp_path) -> None:
    token_file = tmp_path / "spotify-token.json"

    save_token(token_file, {"access_token": "access"})

    assert json.loads(token_file.read_text(encoding="utf-8")) == {"access_token": "access"}
    assert token_file.stat().st_mode & 0o777 == 0o600
