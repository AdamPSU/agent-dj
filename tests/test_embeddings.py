"""Real Deezer preview to MuQ-MuLan embedding integration tests."""

from claude_dj.adapters.deezer import resolve_isrc_preview
from claude_dj.audio.embeddings import generate_audio_embeddings
from claude_dj.storage.db import (
    EMBEDDING_DIMENSIONS,
    connect,
    initialize_schema,
    upsert_preview_match,
    upsert_track,
)


def test_generate_audio_embeddings_stores_real_muq_mulan_vector(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(db)
        track_id = upsert_track(
            db,
            spotify_track_id="spotify-track-bad-guy",
            spotify_uri="spotify:track:bad-guy",
            isrc="USUM71900764",
            title="bad guy",
            artist_name="Billie Eilish",
            album_name="WHEN WE ALL FALL ASLEEP, WHERE DO WE GO?",
            duration_ms=194088,
            explicit=False,
            popularity=None,
        )
        preview = resolve_isrc_preview("USUM71900764")
        assert preview.status == "matched"
        assert preview.preview_url is not None
        upsert_preview_match(
            db,
            track_id=track_id,
            provider="deezer",
            provider_track_id=preview.provider_track_id,
            preview_url=preview.preview_url,
            match_method="isrc",
            confidence=1.0,
            status=preview.status,
            failure_reason=preview.failure_reason,
        )
        db.commit()

        summary = generate_audio_embeddings(db, max_tracks=1)

        metadata = db.execute(
            "SELECT * FROM embedding_metadata WHERE track_id = ?",
            (track_id,),
        ).fetchone()
        embedding_row = db.execute(
            "SELECT track_id FROM track_embeddings WHERE track_id = ?",
            (track_id,),
        ).fetchone()

        assert summary.embedded_count == 1
        assert summary.failed_count == 0
        assert summary.catalog_status.embedding_count == 1
        assert metadata["model_name"] == "OpenMuQ/MuQ-MuLan-large"
        assert metadata["dimensions"] == EMBEDDING_DIMENSIONS
        assert embedding_row["track_id"] == track_id
    finally:
        db.close()
