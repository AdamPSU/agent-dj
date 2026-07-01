"""SQLite persistence and retrieval behavior tests."""

import array

from claude_dj.storage.db import (
    EMBEDDING_DIMENSIONS,
    connect,
    get_catalog_status,
    initialize_schema,
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
        assert status.embedding_count == 0
        assert status.needs_onboarding is True
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
