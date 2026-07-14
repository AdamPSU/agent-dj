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
    monkeypatch.setattr(spotify, "SPOTIFY_CLIENT_ID", "test-client-id")
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


def test_session_is_valid_true_when_me_works(monkeypatch) -> None:
    monkeypatch.setattr(spotify, "get_me", lambda: {"id": "u1"})
    assert spotify.session_is_valid() is True


def test_session_is_valid_false_when_me_fails(monkeypatch) -> None:
    def boom() -> dict:
        raise RuntimeError("expired")

    monkeypatch.setattr(spotify, "get_me", boom)
    assert spotify.session_is_valid() is False


def test_ensure_session_skips_login_when_valid(monkeypatch) -> None:
    monkeypatch.setattr(spotify, "session_is_valid", lambda: True)
    called = {"login": 0}

    def fake_login() -> dict:
        called["login"] += 1
        return {"ok": True}

    monkeypatch.setattr(spotify, "login", fake_login)
    spotify.ensure_session()
    assert called["login"] == 0


def test_ensure_session_relogs_when_invalid(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "spotify_tokens.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(spotify, "SPOTIFY_TOKEN_PATH", path)
    monkeypatch.setattr(spotify, "session_is_valid", lambda: False)
    called = {"login": 0}

    def fake_login() -> dict:
        called["login"] += 1
        path.write_text('{"access_token":"x"}', encoding="utf-8")
        return {"ok": True, "path": str(path)}

    monkeypatch.setattr(spotify, "login", fake_login)
    spotify.ensure_session()
    assert called["login"] == 1
    # stale file cleared before login
    assert path.exists()


def test_iter_top_tracks_params_and_rows(monkeypatch) -> None:
    seen: dict = {}

    def fake_api_get(path: str, params: dict | None = None) -> dict:
        seen["path"] = path
        seen["params"] = params
        return {
            "items": [
                {
                    "id": "t1",
                    "name": "Song",
                    "artists": [{"name": "Artist"}],
                },
                {"id": None, "name": "bad"},
            ]
        }

    monkeypatch.setattr(spotify, "api_get", fake_api_get)
    rows = list(spotify.iter_top_tracks("medium_term", limit=50))
    assert seen["path"] == "/me/top/tracks"
    assert seen["params"] == {"time_range": "medium_term", "limit": 50}
    assert rows == [{"spotify_id": "t1", "name": "Song", "artists": "Artist"}]


def test_scopes_include_user_top_read() -> None:
    from backend.config import SPOTIFY_SCOPES

    assert "user-top-read" in SPOTIFY_SCOPES.split()


def test_get_access_token_requires_client_id_when_expired(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "spotify_tokens.json"
    monkeypatch.setattr(spotify, "SPOTIFY_TOKEN_PATH", path)
    monkeypatch.setattr(spotify, "SPOTIFY_CLIENT_ID", "")
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
    try:
        spotify.get_access_token()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "SPOTIFY_CLIENT_ID" in str(exc)

