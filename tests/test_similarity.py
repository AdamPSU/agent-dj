"""Embedding similarity recommendation tests."""

from claude_dj.recommendation.similarity import SimilarTrack, find_similar_tracks
from claude_dj.storage.db import (
    EMBEDDING_DIMENSIONS,
    connect,
    initialize_schema,
    upsert_track,
    upsert_track_embedding,
)


def test_find_similar_tracks_returns_nearest_neighbors(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        for track_id in (1, 2, 3):
            upsert_track(
                db,
                spotify_track_id=f"spotify-track-{track_id}",
                spotify_uri=f"spotify:track:{track_id}",
                isrc=f"US{track_id}",
                title=f"Track {track_id}",
                artist_name="Artist",
                album_name=None,
                duration_ms=None,
                explicit=False,
                popularity=None,
            )
        upsert_track_embedding(
            db,
            track_id=1,
            embedding=[0.0] * EMBEDDING_DIMENSIONS,
            model_name="OpenMuQ/MuQ-MuLan-large",
            model_version=None,
        )
        upsert_track_embedding(
            db,
            track_id=2,
            embedding=[0.1] * EMBEDDING_DIMENSIONS,
            model_name="OpenMuQ/MuQ-MuLan-large",
            model_version=None,
        )
        upsert_track_embedding(
            db,
            track_id=3,
            embedding=[1.0] * EMBEDDING_DIMENSIONS,
            model_name="OpenMuQ/MuQ-MuLan-large",
            model_version=None,
        )
        db.commit()

        results = find_similar_tracks(db, seed_track_id=1, limit=2)

        assert [result.track_id for result in results] == [2, 3]
        assert all(isinstance(result, SimilarTrack) for result in results)
        assert results[0].distance < results[1].distance
    finally:
        db.close()


def test_find_similar_tracks_returns_empty_when_seed_has_no_embedding(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)

        assert find_similar_tracks(db, seed_track_id=99, limit=10) == []
    finally:
        db.close()
