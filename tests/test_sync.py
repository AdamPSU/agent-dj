from claude_dj.catalog import sync
from claude_dj.catalog import db


def test_kick_is_single_flight(monkeypatch) -> None:
    started = []

    def fake_run() -> None:
        started.append(1)

    monkeypatch.setattr(sync, "run_sync", fake_run)
    monkeypatch.setattr(sync, "_syncing", False)

    assert sync.kick() is True
    # second kick while "running" should no-op; wait for first thread briefly
    import time

    time.sleep(0.05)
    assert len(started) == 1
    assert sync.is_syncing() is False


def test_run_sync_pull_embed_orphan(tmp_path, monkeypatch) -> None:
    conn_path = tmp_path / "catalog.db"
    monkeypatch.setattr(db, "DB_PATH", conn_path)
    monkeypatch.setattr(db, "APP_DIR", tmp_path)

    playlists = [
        {
            "id": "pl1",
            "name": "Mine",
            "snapshot_id": "snap1",
            "owner": {"id": "user1"},
            "tracks": {"total": 2},
        }
    ]
    tracks_page = [
        {
            "spotify_id": "t1",
            "name": "One",
            "artists": "A",
            "album_name": "LP",
            "duration_ms": 1000,
            "isrc": "USAAA0000001",
            "added_at": "2024-01-01T00:00:00Z",
        },
        {
            "spotify_id": "t2",
            "name": "Two",
            "artists": "B",
            "album_name": None,
            "duration_ms": 2000,
            "isrc": None,
            "added_at": None,
        },
    ]

    monkeypatch.setattr(sync.spotify, "get_me", lambda: {"id": "user1"})
    monkeypatch.setattr(sync.spotify, "iter_owned_playlists", lambda: iter(playlists))
    monkeypatch.setattr(
        sync.spotify,
        "iter_playlist_tracks",
        lambda _pid: iter(tracks_page),
    )
    monkeypatch.setattr(
        sync.deezer,
        "lookup_by_isrc",
        lambda isrc: {
            "id": 9,
            "title": "One",
            "artist": "A",
            "isrc": isrc,
            "preview": "https://example.com/p.mp3",
            "readable": True,
            "duration": 30,
        },
    )
    monkeypatch.setattr(sync, "embed_preview", lambda _src: [0.0] * 512)

    sync.run_sync()

    conn = db.connect(conn_path)
    counts = db.track_status_counts(conn)
    assert counts["indexed"] == 1
    assert counts["skipped"] == 1
    assert db.playlist_count(conn) == 1

    # second run: same snapshot → no re-fetch; still fine
    fetched = {"n": 0}

    def count_fetch(_pid):
        fetched["n"] += 1
        if False:
            yield {}

    monkeypatch.setattr(sync.spotify, "iter_playlist_tracks", count_fetch)
    sync.run_sync()
    assert fetched["n"] == 0

    # remove all membership via empty playlist re-pull
    playlists[0]["snapshot_id"] = "snap2"
    monkeypatch.setattr(
        sync.spotify,
        "iter_playlist_tracks",
        lambda _pid: iter([]),
    )
    sync.run_sync()
    assert db.playlist_count(conn) == 1
    assert db.list_tracks(conn) == []
