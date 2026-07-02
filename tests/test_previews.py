"""Preview-resolution orchestration tests."""

from claude_dj.adapters.deezer import DeezerPreviewResult
from claude_dj.audio.previews import (
    DEEZER_RATE_LIMIT_REQUESTS,
    DEEZER_RATE_LIMIT_WINDOW_SECONDS,
    DEEZER_REQUESTS_PER_SECOND,
    resolve_deezer_previews,
)
from claude_dj.storage.db import connect, initialize_schema, upsert_track


def test_deezer_rate_limit_defaults_match_community_observed_window() -> None:
    assert DEEZER_RATE_LIMIT_REQUESTS == 50
    assert DEEZER_RATE_LIMIT_WINDOW_SECONDS == 5
    assert DEEZER_REQUESTS_PER_SECOND == 10


def test_resolve_deezer_previews_stores_isrc_matches_and_failures(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")
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
    missing_isrc_track_id = upsert_track(
        db,
        spotify_track_id="spotify-track-2",
        spotify_uri="spotify:track:2",
        isrc=None,
        title="Missing ISRC",
        artist_name="Artist",
        album_name=None,
        duration_ms=None,
        explicit=False,
        popularity=None,
    )

    calls = []

    def fake_resolver(isrc):
        calls.append(isrc)
        return DeezerPreviewResult(
            status="matched",
            provider_track_id="deezer-1",
            preview_url="https://example.com/preview.mp3",
            failure_reason=None,
        )

    try:
        summary = resolve_deezer_previews(db, resolver=fake_resolver, sleep=lambda seconds: None)

        matches = db.execute("SELECT * FROM preview_matches ORDER BY track_id").fetchall()
        status = summary.catalog_status

        assert calls == ["US123"]
        assert summary.resolved_count == 2
        assert summary.matched_count == 1
        assert summary.no_isrc_count == 1
        assert status.preview_match_count == 2
        assert status.preview_pending_count == 0
        assert status.needs_preview_resolution is False
        assert matches[0]["track_id"] == matched_track_id
        assert matches[0]["provider"] == "deezer"
        assert matches[0]["provider_track_id"] == "deezer-1"
        assert matches[0]["preview_url"] == "https://example.com/preview.mp3"
        assert matches[0]["match_method"] == "isrc"
        assert matches[0]["status"] == "matched"
        assert matches[1]["track_id"] == missing_isrc_track_id
        assert matches[1]["status"] == "no_isrc"
        assert matches[1]["failure_reason"] == "missing_isrc"
    finally:
        db.close()


def test_resolve_deezer_previews_skips_cached_preview_matches(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")
    initialize_schema(db)
    track_id = upsert_track(
        db,
        spotify_track_id="spotify-track-1",
        spotify_uri="spotify:track:1",
        isrc="US123",
        title="Cached",
        artist_name="Artist",
        album_name=None,
        duration_ms=None,
        explicit=False,
        popularity=None,
    )
    db.execute(
        """
        INSERT INTO preview_matches (
          track_id,
          provider,
          provider_track_id,
          preview_url,
          match_method,
          confidence,
          status
        ) VALUES (?, 'deezer', 'deezer-1', 'https://example.com/old.mp3', 'isrc', 1.0, 'matched')
        """,
        (track_id,),
    )
    db.commit()

    def fake_resolver(isrc):
        raise AssertionError("cached tracks should not be resolved again")

    try:
        summary = resolve_deezer_previews(db, resolver=fake_resolver, sleep=lambda seconds: None)

        assert summary.resolved_count == 0
        assert summary.catalog_status.preview_pending_count == 0
    finally:
        db.close()


def test_resolve_deezer_previews_leaves_track_pending_after_rate_limit(tmp_path) -> None:
    db = connect(tmp_path / "claude-dj.sqlite3")
    initialize_schema(db)
    for index, isrc in enumerate(["US123", "US456"], start=1):
        upsert_track(
            db,
            spotify_track_id=f"spotify-track-{index}",
            spotify_uri=f"spotify:track:{index}",
            isrc=isrc,
            title=f"Track {index}",
            artist_name="Artist",
            album_name=None,
            duration_ms=None,
            explicit=False,
            popularity=None,
        )

    calls = []

    def fake_resolver(isrc):
        calls.append(isrc)
        return DeezerPreviewResult(
            status="rate_limited",
            provider_track_id=None,
            preview_url=None,
            failure_reason="deezer_quota_limit",
        )

    try:
        summary = resolve_deezer_previews(db, resolver=fake_resolver, sleep=lambda seconds: None)

        assert calls == ["US123"]
        assert summary.resolved_count == 0
        assert summary.rate_limited_count == 1
        assert summary.catalog_status.preview_match_count == 0
        assert summary.catalog_status.preview_pending_count == 2
        assert summary.catalog_status.needs_preview_resolution is True
    finally:
        db.close()
