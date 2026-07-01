"""SQLite persistence and retrieval behavior tests."""

import array

from claude_dj.storage.db import (
    EMBEDDING_DIMENSIONS,
    connect,
    get_catalog_status,
    initialize_schema,
    replace_source_tracks,
    upsert_source,
    upsert_track,
)


def vector(values: list[float]) -> bytes:
    return array.array("f", values).tobytes()


def test_initialize_schema_creates_metadata_and_vector_tables(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)

        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual')"
            )
        }
        assert "tracks" in tables
        assert "sources" in tables
        assert "source_tracks" in tables
        assert "preview_matches" in tables
        assert "track_embeddings" in tables
        assert "embedding_metadata" in tables
        assert "index_runs" not in tables
        assert "track_index_status" not in tables
    finally:
        db.close()


def test_catalog_status_reports_first_run_on_empty_database(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)

        status = get_catalog_status(db)

        assert status.source_count == 0
        assert status.track_count == 0
        assert status.preview_match_count == 0
        assert status.embedding_count == 0
        assert status.needs_spotify_index is True
        assert status.needs_onboarding is True
    finally:
        db.close()


def test_catalog_status_reports_phase_specific_readiness(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        source_id = upsert_source(
            db,
            source_type="spotify_playlist",
            source_id="playlist-1",
            name="Focus",
            description=None,
        )
        track_id = upsert_track(
            db,
            spotify_track_id="spotify-track-1",
            spotify_uri="spotify:track:1",
            isrc="US123",
            title="Track One",
            artist_name="Artist",
            album_name="Album",
            duration_ms=123000,
            explicit=False,
            popularity=50,
        )
        replace_source_tracks(db, source_id, [(track_id, 0, "2024-01-01T00:00:00Z")])

        status = get_catalog_status(db)

        assert status.needs_spotify_index is False
        assert status.needs_preview_resolution is True
        assert status.needs_embeddings is True
        assert status.ready_for_audio_similarity is False
    finally:
        db.close()


def test_upsert_source_track_and_replace_memberships(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        source_id = upsert_source(
            db,
            source_type="spotify_playlist",
            source_id="playlist-1",
            name="Focus",
            description="old",
        )
        updated_source_id = upsert_source(
            db,
            source_type="spotify_playlist",
            source_id="playlist-1",
            name="Focus Updated",
            description="new",
        )
        track_id = upsert_track(
            db,
            spotify_track_id="spotify-track-1",
            spotify_uri="spotify:track:1",
            isrc="US123",
            title="Track One",
            artist_name="Artist",
            album_name="Album",
            duration_ms=123000,
            explicit=False,
            popularity=50,
        )
        updated_track_id = upsert_track(
            db,
            spotify_track_id="spotify-track-1",
            spotify_uri="spotify:track:1",
            isrc="US123",
            title="Track One Updated",
            artist_name="Artist Updated",
            album_name="Album Updated",
            duration_ms=124000,
            explicit=True,
            popularity=51,
        )

        replace_source_tracks(db, source_id, [(track_id, 0, "2024-01-01T00:00:00Z")])
        replace_source_tracks(db, source_id, [(track_id, 3, "2024-02-01T00:00:00Z")])

        source = db.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        track = db.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
        membership = db.execute("SELECT * FROM source_tracks WHERE source_id = ?", (source_id,)).fetchone()

        assert updated_source_id == source_id
        assert updated_track_id == track_id
        assert source["name"] == "Focus Updated"
        assert source["description"] == "new"
        assert track["title"] == "Track One Updated"
        assert track["artist_name"] == "Artist Updated"
        assert track["explicit"] == 1
        assert membership["position"] == 3
        assert membership["added_at"] == "2024-02-01T00:00:00Z"
    finally:
        db.close()


def test_catalog_status_reports_ready_after_playlist_tracks_and_embeddings(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        db.execute(
            """
            INSERT INTO tracks (id, spotify_track_id, spotify_uri, isrc, title, artist_name)
            VALUES (1, 'spotify-track-1', 'spotify:track:1', 'US123', 'Track One', 'Artist')
            """
        )
        db.execute(
            """
            INSERT INTO sources (id, source_type, source_id, name)
            VALUES (1, 'spotify_playlist', 'playlist-1', 'Focus')
            """
        )
        db.execute("INSERT INTO source_tracks (source_id, track_id, position) VALUES (1, 1, 0)")
        db.execute(
            "INSERT INTO track_embeddings (track_id, embedding) VALUES (?, ?)",
            (1, vector([0.0] * EMBEDDING_DIMENSIONS)),
        )
        db.execute(
            """
            INSERT INTO embedding_metadata (track_id, model_name, model_version, dimensions)
            VALUES (1, 'test-model', '0', ?)
            """,
            (EMBEDDING_DIMENSIONS,),
        )
        db.commit()

        status = get_catalog_status(db)

        assert status.source_count == 1
        assert status.track_count == 1
        assert status.preview_match_count == 0
        assert status.embedding_count == 1
        assert status.needs_onboarding is False
    finally:
        db.close()


def test_sqlite_vec_can_query_nearest_neighbors(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        db.execute(
            "INSERT INTO track_embeddings (track_id, embedding) VALUES (?, ?)",
            (1, vector([0.0, 0.0, 0.0, 0.0])),
        )
        db.execute(
            "INSERT INTO track_embeddings (track_id, embedding) VALUES (?, ?)",
            (2, vector([1.0, 1.0, 1.0, 1.0])),
        )

        rows = db.execute(
            """
            SELECT track_id, distance
            FROM track_embeddings
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT 1
            """,
            (vector([0.1, 0.1, 0.1, 0.1]),),
        ).fetchall()

        assert rows[0][0] == 1
    finally:
        db.close()
