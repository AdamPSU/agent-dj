import base64
import hashlib
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend import spotify
from backend.config import SPOTIFY_SCOPES


def test_pkce_pair_is_s256() -> None:
    verifier, challenge = spotify.pkce_pair()
    assert isinstance(verifier, str) and len(verifier) > 20
    digest = hashlib.sha256(verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert challenge == expected


def test_save_and_load_tokens(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(spotify, "SPOTIFY_TOKEN_PATH", tmp_path / "tokens.json")
    monkeypatch.setattr(spotify, "APP_DIR", tmp_path)
    tokens = {
        "access_token": "a",
        "refresh_token": "r",
        "expires_at": time.time() + 3600,
        "scope": SPOTIFY_SCOPES,
    }
    spotify.save_tokens(tokens)
    loaded = spotify.load_tokens()
    assert loaded is not None
    assert loaded["access_token"] == "a"
    # Atomic write ends with a single JSON object + newline.
    assert (tmp_path / "tokens.json").read_text().endswith("\n")


def test_load_tokens_repairs_trailing_junk(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "tokens.json"
    monkeypatch.setattr(spotify, "SPOTIFY_TOKEN_PATH", path)
    monkeypatch.setattr(spotify, "APP_DIR", tmp_path)
    body = {
        "access_token": "a",
        "refresh_token": "r",
        "expires_at": time.time() + 3600,
        "scope": SPOTIFY_SCOPES,
        "token_type": "Bearer",
    }
    path.write_text(json.dumps(body) + "}", encoding="utf-8")
    loaded = spotify.load_tokens()
    assert loaded is not None
    assert loaded["access_token"] == "a"
    assert json.loads(path.read_text())["access_token"] == "a"


def test_get_access_token_refreshes_when_expired(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "tokens.json"
    monkeypatch.setattr(spotify, "SPOTIFY_TOKEN_PATH", path)
    monkeypatch.setattr(spotify, "APP_DIR", tmp_path)
    monkeypatch.setattr(spotify, "SPOTIFY_CLIENT_ID", "cid")
    path.write_text(
        json.dumps(
            {
                "access_token": "old",
                "refresh_token": "ref",
                "expires_at": time.time() - 10,
                "scope": SPOTIFY_SCOPES,
            }
        )
    )

    def fake_refresh(rt: str) -> dict:
        assert rt == "ref"
        return {
            "access_token": "new",
            "refresh_token": "ref",
            "expires_at": time.time() + 3600,
            "scope": SPOTIFY_SCOPES,
            "token_type": "Bearer",
        }

    monkeypatch.setattr(spotify, "refresh_tokens", fake_refresh)
    assert spotify.get_access_token() == "new"
    assert json.loads(path.read_text())["access_token"] == "new"


def test_session_is_valid_true_when_me_works(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(spotify, "SPOTIFY_TOKEN_PATH", tmp_path / "t.json")
    monkeypatch.setattr(spotify, "APP_DIR", tmp_path)
    spotify.save_tokens(
        {
            "access_token": "a",
            "refresh_token": "r",
            "expires_at": time.time() + 3600,
            "scope": SPOTIFY_SCOPES,
        }
    )
    monkeypatch.setattr(spotify, "get_me", lambda: {"id": "u"})
    assert spotify.session_is_valid() is True


def test_session_is_valid_false_when_missing_scope(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(spotify, "SPOTIFY_TOKEN_PATH", tmp_path / "t.json")
    monkeypatch.setattr(spotify, "APP_DIR", tmp_path)
    spotify.save_tokens(
        {
            "access_token": "a",
            "refresh_token": "r",
            "expires_at": time.time() + 3600,
            "scope": "user-read-email",
        }
    )
    assert spotify.session_is_valid() is False


def test_ensure_session_skips_login_when_valid(monkeypatch) -> None:
    monkeypatch.setattr(spotify, "session_is_valid", lambda: True)
    calls: list[str] = []
    monkeypatch.setattr(spotify, "login", lambda: calls.append("login"))
    spotify.ensure_session()
    assert calls == []


def test_ensure_session_relogs_when_invalid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(spotify, "SPOTIFY_TOKEN_PATH", tmp_path / "t.json")
    monkeypatch.setattr(spotify, "APP_DIR", tmp_path)
    spotify.save_tokens(
        {
            "access_token": "a",
            "refresh_token": "r",
            "expires_at": time.time() + 3600,
            "scope": SPOTIFY_SCOPES,
        }
    )
    monkeypatch.setattr(spotify, "session_is_valid", lambda: False)
    calls: list[str] = []
    monkeypatch.setattr(spotify, "login", lambda: calls.append("login") or {"ok": True})
    spotify.ensure_session()
    assert calls == ["login"]
    assert not (tmp_path / "t.json").exists()


def _mock_urlopen(payload: dict | None, *, status: int = 200):
    resp = MagicMock()
    resp.status = status
    if payload is None:
        resp.read.return_value = b""
    else:
        resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_get_now_playing_playing(monkeypatch) -> None:
    payload = {
        "is_playing": True,
        "progress_ms": 102000,
        "item": {
            "id": "abc",
            "name": "Baby",
            "duration_ms": 190000,
            "type": "track",
            "artists": [{"name": "Four Tet"}],
        },
    }
    monkeypatch.setattr(spotify, "get_access_token", lambda: "tok")
    with patch.object(spotify.urllib.request, "urlopen", return_value=_mock_urlopen(payload)):
        row = spotify.get_now_playing()
    assert row == {
        "spotify_id": "abc",
        "name": "Baby",
        "artists": "Four Tet",
        "progress_ms": 102000,
        "duration_ms": 190000,
        "is_playing": True,
    }


def test_get_now_playing_paused(monkeypatch) -> None:
    payload = {
        "is_playing": False,
        "progress_ms": 5000,
        "item": {
            "id": "x",
            "name": "Song",
            "duration_ms": 10000,
            "type": "track",
            "artists": [{"name": "A"}],
        },
    }
    monkeypatch.setattr(spotify, "get_access_token", lambda: "tok")
    with patch.object(spotify.urllib.request, "urlopen", return_value=_mock_urlopen(payload)):
        row = spotify.get_now_playing()
    assert row is not None
    assert row["is_playing"] is False
    assert row["progress_ms"] == 5000


def test_get_now_playing_empty(monkeypatch) -> None:
    monkeypatch.setattr(spotify, "get_access_token", lambda: "tok")
    with patch.object(
        spotify.urllib.request, "urlopen", return_value=_mock_urlopen(None, status=204)
    ):
        assert spotify.get_now_playing() is None


def test_scopes_match_config() -> None:
    assert SPOTIFY_SCOPES == "user-read-playback-state"
