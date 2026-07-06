"""Spotify auth adapter tests."""

import io
import json
import urllib.error
from urllib.parse import parse_qs, urlparse

from claude_dj.adapters.spotify import (
    DEFAULT_SPOTIFY_SCOPES,
    SpotifyAPIAuthError,
    SpotifyAPIForbiddenError,
    SpotifyAuthError,
    SpotifyDevice,
    SpotifyNoActiveDeviceError,
    SpotifyPlaybackForbiddenError,
    SpotifyPlaybackState,
    add_to_queue,
    add_to_queue_with_token,
    build_authorize_url,
    exchange_authorization_code,
    fetch_available_devices,
    fetch_available_devices_with_token,
    fetch_all_playlists,
    fetch_playlist_tracks,
    fetch_playback_state,
    fetch_playback_state_with_token,
    load_token,
    pkce_challenge,
    refresh_access_token,
    save_token,
    start_playback,
    start_playback_with_token,
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


def test_refresh_access_token_posts_pkce_public_client_request(tmp_path) -> None:
    token_file = tmp_path / "spotify-token.json"
    save_token(token_file, {"access_token": "old-access", "refresh_token": "refresh"})
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps({"access_token": "new-access", "expires_in": 3600}).encode(
                "utf-8"
            )

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    config = SpotifyConfig(
        client_id="client-id",
        redirect_uri="http://127.0.0.1:8888/callback",
    )

    token = refresh_access_token(
        config=config,
        token_file=token_file,
        token=load_token(token_file),
        urlopen=fake_urlopen,
    )
    request, timeout = requests[0]
    body = parse_qs(request.data.decode("utf-8"))

    assert timeout == 10
    assert request.full_url == "https://accounts.spotify.com/api/token"
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["refresh"]
    assert body["client_id"] == ["client-id"]
    assert "client_secret" not in body
    assert token["access_token"] == "new-access"
    assert token["refresh_token"] == "refresh"
    assert json.loads(token_file.read_text(encoding="utf-8"))["access_token"] == "new-access"


def test_start_playback_puts_track_uris_on_active_device() -> None:
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    start_playback(
        "access-token",
        ["spotify:track:1", "spotify:track:2"],
        urlopen=fake_urlopen,
    )

    request, timeout = requests[0]
    assert request.full_url == "https://api.spotify.com/v1/me/player/play"
    assert request.get_method() == "PUT"
    assert request.headers["Authorization"] == "Bearer access-token"
    assert request.headers["Content-type"] == "application/json"
    assert json.loads(request.data.decode("utf-8")) == {
        "uris": ["spotify:track:1", "spotify:track:2"]
    }
    assert timeout == 10


def test_start_playback_targets_device_id_when_provided() -> None:
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    start_playback(
        "access-token",
        ["spotify:track:1"],
        device_id="device-1",
        urlopen=fake_urlopen,
    )

    request, _timeout = requests[0]
    assert request.full_url == "https://api.spotify.com/v1/me/player/play?device_id=device-1"
    assert request.get_method() == "PUT"
    assert json.loads(request.data.decode("utf-8")) == {"uris": ["spotify:track:1"]}


def test_start_playback_rejects_empty_uri_list() -> None:
    try:
        start_playback("access-token", [])
    except ValueError as exc:
        assert "Spotify URI" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_start_playback_maps_auth_failure() -> None:
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    try:
        start_playback("access-token", ["spotify:track:1"], urlopen=fake_urlopen)
    except SpotifyAPIAuthError as exc:
        assert "expired or invalid" in str(exc)
    else:
        raise AssertionError("expected SpotifyAPIAuthError")


def test_start_playback_maps_forbidden_response() -> None:
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    try:
        start_playback("access-token", ["spotify:track:1"], urlopen=fake_urlopen)
    except SpotifyPlaybackForbiddenError as exc:
        assert "denied playback control" in str(exc)
    else:
        raise AssertionError("expected SpotifyPlaybackForbiddenError")


def test_start_playback_maps_no_active_device_response() -> None:
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            {},
            io.BytesIO(b'{"error":{"message":"No active device found"}}'),
        )

    try:
        start_playback("access-token", ["spotify:track:1"], urlopen=fake_urlopen)
    except SpotifyNoActiveDeviceError as exc:
        assert "No active Spotify device" in str(exc)
    else:
        raise AssertionError("expected SpotifyNoActiveDeviceError")


def test_fetch_available_devices_normalizes_spotify_connect_devices() -> None:
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "devices": [
                        {
                            "id": "device-1",
                            "name": "MacBook",
                            "type": "Computer",
                            "is_active": False,
                            "is_restricted": False,
                        },
                        {
                            "id": None,
                            "name": "Missing ID",
                            "type": "Computer",
                            "is_active": False,
                            "is_restricted": False,
                        },
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    devices = fetch_available_devices("access-token", urlopen=fake_urlopen)

    request, timeout = requests[0]
    assert request.full_url == "https://api.spotify.com/v1/me/player/devices"
    assert request.get_method() == "GET"
    assert request.headers["Authorization"] == "Bearer access-token"
    assert timeout == 10
    assert devices == [
        SpotifyDevice(
            id="device-1",
            name="MacBook",
            type="Computer",
            is_active=False,
            is_restricted=False,
        )
    ]


def test_fetch_playback_state_normalizes_current_track() -> None:
    requests = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "is_playing": True,
                    "item": {
                        "type": "track",
                        "uri": "spotify:track:1",
                    },
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    state = fetch_playback_state("access-token", urlopen=fake_urlopen)

    request, timeout = requests[0]
    assert request.full_url == "https://api.spotify.com/v1/me/player"
    assert request.get_method() == "GET"
    assert request.headers["Authorization"] == "Bearer access-token"
    assert timeout == 10
    assert state == SpotifyPlaybackState(item_uri="spotify:track:1", is_playing=True)


def test_fetch_playback_state_returns_idle_when_spotify_has_no_playback() -> None:
    class FakeResponse:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b""

    def fake_urlopen(request, timeout):
        return FakeResponse()

    state = fetch_playback_state("access-token", urlopen=fake_urlopen)

    assert state == SpotifyPlaybackState(item_uri=None, is_playing=False)


def test_add_to_queue_posts_track_uri_to_active_device() -> None:
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    add_to_queue("access-token", "spotify:track:1", device_id="device-1", urlopen=fake_urlopen)

    request, timeout = requests[0]
    parsed = urlparse(request.full_url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "api.spotify.com"
    assert parsed.path == "/v1/me/player/queue"
    assert request.get_method() == "POST"
    assert request.headers["Authorization"] == "Bearer access-token"
    assert query == {"uri": ["spotify:track:1"], "device_id": ["device-1"]}
    assert timeout == 10


def test_fetch_playback_state_with_token_refreshes_once_on_expired_access_token(tmp_path) -> None:
    token_file = tmp_path / "spotify-token.json"
    save_token(token_file, {"access_token": "old-access", "refresh_token": "refresh"})
    playback_tokens = []

    class FakeResponse:
        def __init__(self, payload=None):
            self.payload = payload or {}
            self.status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        if request.full_url == "https://api.spotify.com/v1/me/player":
            playback_tokens.append(request.headers["Authorization"])
            if len(playback_tokens) == 1:
                raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)
            return FakeResponse({"is_playing": False, "item": None})
        if request.full_url == "https://accounts.spotify.com/api/token":
            return FakeResponse({"access_token": "new-access", "expires_in": 3600})
        raise AssertionError(f"unexpected URL {request.full_url}")

    state = fetch_playback_state_with_token(
        config=SpotifyConfig(client_id="client-id", redirect_uri="http://127.0.0.1:8888/callback"),
        token_file=token_file,
        urlopen=fake_urlopen,
    )

    assert state == SpotifyPlaybackState(item_uri=None, is_playing=False)
    assert playback_tokens == ["Bearer old-access", "Bearer new-access"]


def test_add_to_queue_with_token_refreshes_once_on_expired_access_token(tmp_path) -> None:
    token_file = tmp_path / "spotify-token.json"
    save_token(token_file, {"access_token": "old-access", "refresh_token": "refresh"})
    queue_tokens = []

    class FakeResponse:
        def __init__(self, payload=None):
            self.payload = payload or {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        if request.full_url.startswith("https://api.spotify.com/v1/me/player/queue"):
            queue_tokens.append(request.headers["Authorization"])
            if len(queue_tokens) == 1:
                raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)
            return FakeResponse()
        if request.full_url == "https://accounts.spotify.com/api/token":
            return FakeResponse({"access_token": "new-access", "expires_in": 3600})
        raise AssertionError(f"unexpected URL {request.full_url}")

    add_to_queue_with_token(
        config=SpotifyConfig(client_id="client-id", redirect_uri="http://127.0.0.1:8888/callback"),
        token_file=token_file,
        spotify_uri="spotify:track:1",
        urlopen=fake_urlopen,
    )

    assert queue_tokens == ["Bearer old-access", "Bearer new-access"]


def test_start_playback_with_token_refreshes_once_on_expired_access_token(tmp_path) -> None:
    token_file = tmp_path / "spotify-token.json"
    save_token(token_file, {"access_token": "old-access", "refresh_token": "refresh"})
    playback_tokens = []

    class FakeResponse:
        def __init__(self, payload=None):
            self.payload = payload or {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        if request.full_url == "https://api.spotify.com/v1/me/player/play":
            playback_tokens.append(request.headers["Authorization"])
            if len(playback_tokens) == 1:
                raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)
            return FakeResponse()
        if request.full_url == "https://accounts.spotify.com/api/token":
            return FakeResponse({"access_token": "new-access", "expires_in": 3600})
        raise AssertionError(f"unexpected URL {request.full_url}")

    start_playback_with_token(
        config=SpotifyConfig(client_id="client-id", redirect_uri="http://127.0.0.1:8888/callback"),
        token_file=token_file,
        spotify_uris=["spotify:track:1"],
        urlopen=fake_urlopen,
    )

    assert playback_tokens == ["Bearer old-access", "Bearer new-access"]
    assert json.loads(token_file.read_text(encoding="utf-8"))["access_token"] == "new-access"


def test_fetch_available_devices_with_token_refreshes_once_on_expired_access_token(tmp_path) -> None:
    token_file = tmp_path / "spotify-token.json"
    save_token(token_file, {"access_token": "old-access", "refresh_token": "refresh"})
    device_tokens = []

    class FakeResponse:
        def __init__(self, payload=None):
            self.payload = payload or {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        if request.full_url == "https://api.spotify.com/v1/me/player/devices":
            device_tokens.append(request.headers["Authorization"])
            if len(device_tokens) == 1:
                raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)
            return FakeResponse({"devices": []})
        if request.full_url == "https://accounts.spotify.com/api/token":
            return FakeResponse({"access_token": "new-access", "expires_in": 3600})
        raise AssertionError(f"unexpected URL {request.full_url}")

    devices = fetch_available_devices_with_token(
        config=SpotifyConfig(client_id="client-id", redirect_uri="http://127.0.0.1:8888/callback"),
        token_file=token_file,
        urlopen=fake_urlopen,
    )

    assert devices == []
    assert device_tokens == ["Bearer old-access", "Bearer new-access"]


def test_start_playback_with_token_does_not_require_config_for_valid_token(tmp_path) -> None:
    token_file = tmp_path / "spotify-token.json"
    save_token(token_file, {"access_token": "access"})
    playback_tokens = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_urlopen(request, timeout):
        playback_tokens.append(request.headers["Authorization"])
        return FakeResponse()

    start_playback_with_token(
        token_file=token_file,
        spotify_uris=["spotify:track:1"],
        urlopen=fake_urlopen,
    )

    assert playback_tokens == ["Bearer access"]


def test_start_playback_with_token_requires_spotify_login(tmp_path) -> None:
    try:
        start_playback_with_token(
            config=SpotifyConfig(client_id="client-id", redirect_uri="http://127.0.0.1:8888/callback"),
            token_file=tmp_path / "missing-token.json",
            spotify_uris=["spotify:track:1"],
        )
    except SpotifyAuthError as exc:
        assert "Spotify login is required before playback" in str(exc)
    else:
        raise AssertionError("expected SpotifyAuthError")


def test_fetch_all_playlists_paginates_current_user_playlists() -> None:
    requests = []
    pages = {
        "https://api.spotify.com/v1/me/playlists?limit=50": {
            "items": [{"id": "playlist-1", "name": "One", "description": "First"}],
            "next": "https://api.spotify.com/v1/me/playlists?limit=50&offset=50",
        },
        "https://api.spotify.com/v1/me/playlists?limit=50&offset=50": {
            "items": [{"id": "playlist-2", "name": "Two", "description": None}],
            "next": None,
        },
    }

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse(pages[request.full_url])

    playlists = fetch_all_playlists("access-token", urlopen=fake_urlopen)

    assert [playlist.id for playlist in playlists] == ["playlist-1", "playlist-2"]
    assert [playlist.name for playlist in playlists] == ["One", "Two"]
    assert requests[0].headers["Authorization"] == "Bearer access-token"


def test_fetch_playlist_tracks_paginates_and_normalizes_tracks() -> None:
    pages = {
        "https://api.spotify.com/v1/playlists/playlist-1/items?limit=100&offset=0": {
            "items": [
                {
                    "added_at": "2024-01-01T00:00:00Z",
                    "is_local": False,
                    "track": {
                        "type": "track",
                        "id": "track-1",
                        "uri": "spotify:track:1",
                        "name": "Song",
                        "artists": [{"name": "Artist"}],
                        "album": {"name": "Album"},
                        "duration_ms": 123000,
                        "explicit": True,
                        "popularity": 42,
                        "external_ids": {"isrc": "US123"},
                    },
                },
                {
                    "added_at": "2024-01-02T00:00:00Z",
                    "is_local": True,
                    "track": None,
                },
            ],
            "next": "https://api.spotify.com/v1/playlists/playlist-1/items?limit=100&offset=100",
        },
        "https://api.spotify.com/v1/playlists/playlist-1/items?limit=100&offset=100": {
            "items": [
                {
                    "added_at": "2024-01-03T00:00:00Z",
                    "is_local": False,
                    "track": {"type": "episode", "id": "episode-1"},
                }
            ],
            "next": None,
        },
    }

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        return FakeResponse(pages[request.full_url])

    tracks = fetch_playlist_tracks("access-token", "playlist-1", urlopen=fake_urlopen)

    assert len(tracks) == 1
    assert tracks[0].position == 0
    assert tracks[0].added_at == "2024-01-01T00:00:00Z"
    assert tracks[0].track.spotify_track_id == "track-1"
    assert tracks[0].track.spotify_uri == "spotify:track:1"
    assert tracks[0].track.isrc == "US123"
    assert tracks[0].track.title == "Song"
    assert tracks[0].track.artist_name == "Artist"
    assert tracks[0].track.album_name == "Album"
    assert tracks[0].track.explicit is True


def test_fetch_playlist_tracks_maps_forbidden_response() -> None:
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    try:
        fetch_playlist_tracks("access-token", "playlist-1", urlopen=fake_urlopen)
    except SpotifyAPIForbiddenError as exc:
        assert "denied" in str(exc)
    else:
        raise AssertionError("expected SpotifyAPIForbiddenError")


def test_fetch_playlist_tracks_normalizes_current_items_shape() -> None:
    pages = {
        "https://api.spotify.com/v1/playlists/playlist-1/items?limit=100&offset=0": {
            "items": [
                {
                    "added_at": "2024-01-01T00:00:00Z",
                    "is_local": False,
                    "item": {
                        "type": "track",
                        "id": "track-1",
                        "uri": "spotify:track:1",
                        "name": "Song",
                        "artists": [{"name": "Artist"}],
                        "album": {"name": "Album"},
                        "duration_ms": 123000,
                        "explicit": False,
                        "popularity": 42,
                        "external_ids": {"isrc": "US123"},
                    },
                }
            ],
            "next": None,
        },
    }

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        return FakeResponse(pages[request.full_url])

    tracks = fetch_playlist_tracks("access-token", "playlist-1", urlopen=fake_urlopen)

    assert len(tracks) == 1
    assert tracks[0].track.spotify_track_id == "track-1"
    assert tracks[0].track.title == "Song"
