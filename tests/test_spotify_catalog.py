from unittest.mock import patch

from claude_dj.adapters import spotify


def test_iter_owned_playlists_filters_owner(monkeypatch) -> None:
    pages = [
        {
            "items": [
                {"id": "mine", "name": "Mine", "owner": {"id": "u1"}},
                {"id": "theirs", "name": "Theirs", "owner": {"id": "u2"}},
            ],
            "next": None,
        }
    ]

    monkeypatch.setattr(spotify, "get_me", lambda: {"id": "u1"})
    monkeypatch.setattr(spotify, "api_get", lambda path, params=None: pages[0])
    owned = list(spotify.iter_owned_playlists())
    assert [p["id"] for p in owned] == ["mine"]


def test_iter_playlist_tracks_skips_junk(monkeypatch) -> None:
    payload = {
        "items": [
            {"is_local": True, "item": {"id": "local", "type": "track", "name": "L"}},
            {"item": None},
            {
                "added_at": "2024-01-01T00:00:00Z",
                "item": {
                    "id": "ok",
                    "type": "track",
                    "name": "Song",
                    "artists": [{"name": "A"}, {"name": "B"}],
                    "album": {"name": "LP"},
                    "duration_ms": 123,
                    "external_ids": {"isrc": "USAAA0000001"},
                    "is_local": False,
                },
            },
            {
                "item": {
                    "id": "ep",
                    "type": "episode",
                    "name": "Pod",
                    "artists": [],
                }
            },
        ],
        "next": None,
    }
    monkeypatch.setattr(spotify, "api_get", lambda path, params=None: payload)
    rows = list(spotify.iter_playlist_tracks("pl"))
    assert len(rows) == 1
    assert rows[0]["spotify_id"] == "ok"
    assert rows[0]["artists"] == "A, B"
    assert rows[0]["isrc"] == "USAAA0000001"
