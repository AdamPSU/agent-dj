"""SQLite persistence and retrieval behavior tests."""

import array

from claude_dj.storage.db import (
    EMBEDDING_DIMENSIONS,
    PlayableTrack,
    TrackEmbeddingCandidate,
    connect,
    fetch_tracks_by_ids,
    fetch_tracks_needing_preview_resolution,
    fetch_tracks_needing_embeddings,
    get_catalog_status,
    initialize_schema,
    replace_source_tracks,
    upsert_preview_match,
    upsert_source,
    upsert_track_embedding,
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
        assert EMBEDDING_DIMENSIONS == 1024
        preview_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(preview_matches)")
        }
        assert "confidence" not in preview_columns
    finally:
        db.close()


def test_initialize_schema_replaces_placeholder_embedding_dimensions(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        db.execute(
            "CREATE VIRTUAL TABLE track_embeddings USING vec0(track_id INTEGER PRIMARY KEY, embedding FLOAT[4])"
        )
        db.execute(
            """
            CREATE TABLE embedding_metadata (
              track_id INTEGER PRIMARY KEY,
              model_name TEXT NOT NULL,
              model_version TEXT,
              dimensions INTEGER NOT NULL
            )
            """
        )

        initialize_schema(db)

        sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'track_embeddings'"
        ).fetchone()["sql"]
        db.execute(
            "INSERT INTO track_embeddings (track_id, embedding) VALUES (?, ?)",
            (1, vector([0.0] * EMBEDDING_DIMENSIONS)),
        )

        assert f"FLOAT[{EMBEDDING_DIMENSIONS}]" in sql
    finally:
        db.close()


def test_initialize_schema_replaces_incompatible_embedding_model_with_same_dimensions(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        db.execute(
            f"CREATE VIRTUAL TABLE track_embeddings USING vec0(track_id INTEGER PRIMARY KEY, embedding FLOAT[{EMBEDDING_DIMENSIONS}])"
        )
        db.execute(
            """
            CREATE TABLE embedding_metadata (
              track_id INTEGER PRIMARY KEY,
              model_name TEXT NOT NULL,
              model_version TEXT,
              dimensions INTEGER NOT NULL
            )
            """
        )
        db.execute(
            "INSERT INTO track_embeddings (track_id, embedding) VALUES (?, ?)",
            (1, vector([0.0] * EMBEDDING_DIMENSIONS)),
        )
        db.execute(
            """
            INSERT INTO embedding_metadata (track_id, model_name, model_version, dimensions)
            VALUES (1, 'OpenMuQ/MuQ-large-msd-iter', NULL, ?)
            """,
            (EMBEDDING_DIMENSIONS,),
        )

        initialize_schema(
            db,
            dimensions=EMBEDDING_DIMENSIONS,
            model_name="legacy-audio-model",
            model_version=None,
        )

        assert db.execute("SELECT COUNT(*) FROM track_embeddings").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM embedding_metadata").fetchone()[0] == 0
    finally:
        db.close()


def test_catalog_status_reports_first_run_on_empty_database(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)

        status = get_catalog_status(db)
        payload = status.to_json()

        assert status.source_count == 0
        assert status.track_count == 0
        assert status.preview_match_count == 0
        assert status.embedding_count == 0
        assert status.needs_spotify_index is True
        assert status.needs_onboarding is True
        assert "ready_track_count" not in payload
        assert "ready_for_audio_similarity" not in payload
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
        assert status.needs_embeddings is False
    finally:
        db.close()


def test_fetch_tracks_by_ids_returns_playable_tracks_in_requested_order(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        first_id = upsert_track(
            db,
            spotify_track_id="spotify-track-1",
            spotify_uri="spotify:track:1",
            isrc="US123",
            title="Track One",
            artist_name="Artist One",
            album_name="Album",
            duration_ms=123000,
            explicit=False,
            popularity=50,
        )
        second_id = upsert_track(
            db,
            spotify_track_id="spotify-track-2",
            spotify_uri="spotify:track:2",
            isrc="US456",
            title="Track Two",
            artist_name="Artist Two",
            album_name="Album",
            duration_ms=124000,
            explicit=False,
            popularity=51,
        )
        db.commit()

        tracks = fetch_tracks_by_ids(db, [second_id, 999, first_id, second_id])

        assert tracks == [
            PlayableTrack(
                track_id=second_id,
                spotify_uri="spotify:track:2",
                title="Track Two",
                artist_name="Artist Two",
            ),
            PlayableTrack(
                track_id=first_id,
                spotify_uri="spotify:track:1",
                title="Track One",
                artist_name="Artist One",
            ),
        ]
    finally:
        db.close()


def test_catalog_status_needs_preview_resolution_until_all_tracks_have_preview_rows(tmp_path) -> None:
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
        embedded_track_id = upsert_track(
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
        pending_track_id = upsert_track(
            db,
            spotify_track_id="spotify-track-2",
            spotify_uri="spotify:track:2",
            isrc="US456",
            title="Track Two",
            artist_name="Artist",
            album_name="Album",
            duration_ms=124000,
            explicit=False,
            popularity=51,
        )
        replace_source_tracks(
            db,
            source_id,
            [
                (embedded_track_id, 0, "2024-01-01T00:00:00Z"),
                (pending_track_id, 1, "2024-01-01T00:00:00Z"),
            ],
        )
        upsert_preview_match(
            db,
            track_id=embedded_track_id,
            provider="deezer",
            provider_track_id="deezer-1",
            preview_url="https://example.com/preview.mp3",
            match_method="isrc",
            status="matched",
            failure_reason=None,
        )
        upsert_track_embedding(
            db,
            track_id=embedded_track_id,
            embedding=[1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1),
            model_name="OpenMuQ/MuQ-large-msd-iter",
            model_version=None,
        )

        status = get_catalog_status(db)

        assert status.preview_pending_count == 1
        assert status.embedding_count == 1
        assert status.needs_preview_resolution is True
        assert status.needs_onboarding is True
    finally:
        db.close()


def test_preview_resolution_refreshes_matched_urls_until_embedding_exists(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
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
        upsert_preview_match(
            db,
            track_id=track_id,
            provider="deezer",
            provider_track_id="deezer-1",
            preview_url="https://example.com/stale-preview.mp3",
            match_method="isrc",
            status="matched",
            failure_reason=None,
        )
        db.commit()

        candidates = fetch_tracks_needing_preview_resolution(db)

        assert candidates[0].track_id == track_id
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


def test_catalog_status_reports_embedded_but_still_onboarding_without_preview_rows(tmp_path) -> None:
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
        assert status.needs_preview_resolution is True
        assert status.needs_onboarding is True
    finally:
        db.close()


def test_fetch_tracks_needing_embeddings_returns_matched_preview_urls(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        matched_track_id = upsert_track(
            db,
            spotify_track_id="spotify-track-1",
            spotify_uri="spotify:track:1",
            isrc="US123",
            title="Matched",
            artist_name="Artist",
            album_name=None,
            duration_ms=None,
            explicit=False,
            popularity=None,
        )
        failed_track_id = upsert_track(
            db,
            spotify_track_id="spotify-track-2",
            spotify_uri="spotify:track:2",
            isrc="US456",
            title="Failed",
            artist_name="Artist",
            album_name=None,
            duration_ms=None,
            explicit=False,
            popularity=None,
        )
        upsert_preview_match(
            db,
            track_id=matched_track_id,
            provider="deezer",
            provider_track_id="deezer-1",
            preview_url="https://example.com/preview.mp3",
            match_method="isrc",
            status="matched",
            failure_reason=None,
        )
        upsert_preview_match(
            db,
            track_id=failed_track_id,
            provider="deezer",
            provider_track_id=None,
            preview_url=None,
            match_method="isrc",
            status="not_found",
            failure_reason="deezer_no_data",
        )
        db.commit()

        candidates = fetch_tracks_needing_embeddings(db)

        assert candidates == [
            TrackEmbeddingCandidate(
                track_id=matched_track_id,
                preview_url="https://example.com/preview.mp3",
            )
        ]
    finally:
        db.close()


def test_upsert_track_embedding_stores_vector_and_metadata(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        track_id = upsert_track(
            db,
            spotify_track_id="spotify-track-1",
            spotify_uri="spotify:track:1",
            isrc="US123",
            title="Matched",
            artist_name="Artist",
            album_name=None,
            duration_ms=None,
            explicit=False,
            popularity=None,
        )
        upsert_preview_match(
            db,
            track_id=track_id,
            provider="deezer",
            provider_track_id="deezer-1",
            preview_url="https://example.com/preview.mp3",
            match_method="isrc",
            status="matched",
            failure_reason=None,
        )

        upsert_track_embedding(
            db,
            track_id=track_id,
            embedding=[0.25] * EMBEDDING_DIMENSIONS,
            model_name="OpenMuQ/MuQ-large-msd-iter",
            model_version=None,
            dimensions=EMBEDDING_DIMENSIONS,
        )
        db.commit()

        status = get_catalog_status(db)
        metadata = db.execute(
            "SELECT * FROM embedding_metadata WHERE track_id = ?",
            (track_id,),
        ).fetchone()
        candidates = fetch_tracks_needing_embeddings(db)

        assert status.embedding_count == 1
        assert metadata["model_name"] == "OpenMuQ/MuQ-large-msd-iter"
        assert metadata["model_version"] is None
        assert metadata["dimensions"] == EMBEDDING_DIMENSIONS
        assert candidates == []
    finally:
        db.close()


def test_catalog_status_reports_embedding_pending_for_matched_previews_only(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        matched_track_id = upsert_track(
            db,
            spotify_track_id="spotify-track-1",
            spotify_uri="spotify:track:1",
            isrc="US123",
            title="Matched",
            artist_name="Artist",
            album_name=None,
            duration_ms=None,
            explicit=False,
            popularity=None,
        )
        failed_track_id = upsert_track(
            db,
            spotify_track_id="spotify-track-2",
            spotify_uri="spotify:track:2",
            isrc="US456",
            title="Failed",
            artist_name="Artist",
            album_name=None,
            duration_ms=None,
            explicit=False,
            popularity=None,
        )
        upsert_preview_match(
            db,
            track_id=matched_track_id,
            provider="deezer",
            provider_track_id="deezer-1",
            preview_url="https://example.com/preview.mp3",
            match_method="isrc",
            status="matched",
            failure_reason=None,
        )
        upsert_preview_match(
            db,
            track_id=failed_track_id,
            provider="deezer",
            provider_track_id=None,
            preview_url=None,
            match_method="isrc",
            status="not_found",
            failure_reason="deezer_no_data",
        )
        db.commit()

        status = get_catalog_status(db)

        assert status.embedding_pending_count == 1
        assert status.needs_embeddings is True

        upsert_track_embedding(
            db,
            track_id=matched_track_id,
            embedding=[0.25] * EMBEDDING_DIMENSIONS,
            model_name="OpenMuQ/MuQ-large-msd-iter",
            model_version=None,
            dimensions=EMBEDDING_DIMENSIONS,
        )
        db.commit()

        status = get_catalog_status(db)

        assert status.embedding_pending_count == 0
        assert status.needs_embeddings is False
    finally:
        db.close()


def test_sqlite_vec_can_query_nearest_neighbors(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        db.execute(
            "INSERT INTO track_embeddings (track_id, embedding) VALUES (?, ?)",
            (1, vector([0.0] * EMBEDDING_DIMENSIONS)),
        )
        db.execute(
            "INSERT INTO track_embeddings (track_id, embedding) VALUES (?, ?)",
            (2, vector([1.0] * EMBEDDING_DIMENSIONS)),
        )

        rows = db.execute(
            """
            SELECT track_id, distance
            FROM track_embeddings
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT 1
            """,
            (vector([0.1] * EMBEDDING_DIMENSIONS),),
        ).fetchall()

        assert rows[0][0] == 1
    finally:
        db.close()
