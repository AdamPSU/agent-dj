"""Spotify playlist indexing orchestration tests."""

import json

from claude_dj.indexing import index_spotify_playlists
from claude_dj.storage.db import connect, initialize_schema


def test_index_spotify_playlists_stores_sources_tracks_and_memberships(tmp_path) -> None:
    token_file = tmp_path / "spotify-token.json"
    token_file.write_text(json.dumps({"access_token": "access-token"}), encoding="utf-8")
    db = connect(tmp_path / "claude-dj.sqlite3")
    initialize_schema(db)

    pages = {
        "https://api.spotify.com/v1/me/playlists?limit=50": {
            "items": [{"id": "playlist-1", "name": "Focus", "description": "Work"}],
            "next": None,
        },
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
                        "explicit": False,
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

    try:
        summary = index_spotify_playlists(db, token_file=token_file, urlopen=fake_urlopen)

        source = db.execute("SELECT * FROM sources").fetchone()
        track = db.execute("SELECT * FROM tracks").fetchone()
        membership = db.execute("SELECT * FROM source_tracks").fetchone()

        assert summary.playlist_count == 1
        assert summary.track_count == 1
        assert summary.skipped_track_count == 1
        assert summary.catalog_status.needs_spotify_index is False
        assert source["source_type"] == "spotify_playlist"
        assert source["source_id"] == "playlist-1"
        assert source["name"] == "Focus"
        assert track["spotify_track_id"] == "track-1"
        assert track["isrc"] == "US123"
        assert membership["source_id"] == source["id"]
        assert membership["track_id"] == track["id"]
        assert membership["position"] == 0
    finally:
        db.close()
