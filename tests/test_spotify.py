import base64
import hashlib
import json
import time
from pathlib import Path

from backend.adapters import spotify


def test_pkce_pair_is_s256() -> None:
    verifier, challenge = spotify.pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == expected
    assert len(verifier) > 40


def test_save_and_load_tokens(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "spotify_tokens.json"
    monkeypatch.setattr(spotify, "APP_DIR", tmp_path)
    monkeypatch.setattr(spotify, "SPOTIFY_TOKEN_PATH", path)
    tokens = {
        "access_token": "a",
        "refresh_token": "r",
        "expires_at": time.time() + 1000,
        "scope": "x",
        "token_type": "Bearer",
    }
    spotify.save_tokens(tokens)
    assert path.stat().st_mode & 0o777 == 0o600
    assert spotify.load_tokens() == tokens
    assert spotify.tokens_missing() is False


def test_get_access_token_refreshes_when_expired(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "spotify_tokens.json"
    monkeypatch.setattr(spotify, "APP_DIR", tmp_path)
    monkeypatch.setattr(spotify, "SPOTIFY_TOKEN_PATH", path)
    path.write_text(
        json.dumps(
            {
                "access_token": "old",
                "refresh_token": "r",
                "expires_at": time.time() - 10,
                "scope": "x",
                "token_type": "Bearer",
            }
        ),
        encoding="utf-8",
    )

    def fake_refresh(refresh_token: str) -> dict:
        assert refresh_token == "r"
        return {
            "access_token": "new",
            "refresh_token": "r2",
            "expires_at": time.time() + 1000,
            "scope": "x",
            "token_type": "Bearer",
        }

    monkeypatch.setattr(spotify, "refresh_tokens", fake_refresh)
    assert spotify.get_access_token() == "new"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["access_token"] == "new"
    assert saved["refresh_token"] == "r2"


def test_authorize_url_requires_client_id(monkeypatch) -> None:
    monkeypatch.setattr(spotify, "SPOTIFY_CLIENT_ID", "")
    try:
        spotify.authorize_url("state", "challenge", "http://127.0.0.1:1/callback")
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert "SPOTIFY_CLIENT_ID" in str(exc)


def test_tokens_missing_when_absent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(spotify, "SPOTIFY_TOKEN_PATH", tmp_path / "missing.json")
    assert spotify.tokens_missing() is True
