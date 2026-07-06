"""Local daemon HTTP endpoint tests."""

import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from claude_dj.daemon import MIN_READY_TRACKS, create_server, write_runtime_file
from claude_dj.audio.embeddings import EmbeddingGenerationSummary
from claude_dj.config import LOCAL_MUQ_DIMENSIONS, LOCAL_MUQ_MODEL_NAME, get_embedding_config
from claude_dj.audio.previews import PreviewResolutionSummary
from claude_dj.indexing import (
    IndexSummary,
    SpotifyIndexingAccessDenied,
    SpotifyIndexingAuthRequired,
)
from claude_dj.recommendation.similarity import DJBlock, DJTrack
from claude_dj.storage.db import CatalogStatus, connect, initialize_schema, upsert_track, upsert_track_embedding


LEGACY_EMBEDDING_MODEL_NAME = "legacy-audio-model"
LEGACY_EMBEDDING_DIMENSIONS = 512


def test_min_ready_tracks_for_dj_start_is_30() -> None:
    assert MIN_READY_TRACKS == 30


def test_daemon_schema_initialization_invalidates_legacy_embeddings(tmp_path) -> None:
    from claude_dj.daemon import _initialize_embedding_schema

    db = connect(tmp_path / "claude-dj.sqlite3")

    try:
        initialize_schema(
            db,
            dimensions=LEGACY_EMBEDDING_DIMENSIONS,
            model_name=LEGACY_EMBEDDING_MODEL_NAME,
            model_version=None,
        )
        track_id = upsert_track(
            db,
            spotify_track_id="spotify-track-1",
            spotify_uri="spotify:track:1",
            isrc="US123",
            title="Legacy Track",
            artist_name="Artist",
            album_name=None,
            duration_ms=None,
            explicit=False,
            popularity=None,
        )
        upsert_track_embedding(
            db,
            track_id=track_id,
            embedding=[1.0] + [0.0] * (LEGACY_EMBEDDING_DIMENSIONS - 1),
            model_name=LEGACY_EMBEDDING_MODEL_NAME,
            model_version=None,
            dimensions=LEGACY_EMBEDDING_DIMENSIONS,
        )
        db.commit()

        _initialize_embedding_schema(db, get_embedding_config())

        schema = db.execute("SELECT sql FROM sqlite_master WHERE name = 'track_embeddings'").fetchone()
        embedding_count = db.execute("SELECT COUNT(*) AS count FROM track_embeddings").fetchone()

        assert f"FLOAT[{LOCAL_MUQ_DIMENSIONS}]" in schema["sql"]
        assert embedding_count["count"] == 0
    finally:
        db.close()


def start_test_server():
    server = create_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop_test_server(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def json_request(method: str, url: str, body: dict | None = None) -> dict:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=2) as response:
        assert response.headers["Content-Type"] == "application/json"
        return json.loads(response.read().decode("utf-8"))


def test_server_binds_to_loopback_dynamic_port() -> None:
    server = create_server()

    try:
        host, port = server.server_address

        assert host == "127.0.0.1"
        assert port > 0
    finally:
        server.server_close()


def test_status_endpoint_returns_daemon_state() -> None:
    server, thread = start_test_server()

    try:
        host, port = server.server_address

        response = json_request("GET", f"http://{host}:{port}/status")

        assert response["ok"] is True
        assert response["status"] == "running"
        assert response["host"] == "127.0.0.1"
        assert response["pid"] == os.getpid()
    finally:
        stop_test_server(server, thread)


def test_status_endpoint_returns_sync_and_indexing_state() -> None:
    server, thread = start_test_server()

    try:
        host, port = server.server_address
        server.state.sync_status = "failed"
        server.state.sync_error = "Could not generate MuQ embedding."
        server.state.sync_indexing = {
            "spotify": {"ran": True, "playlist_count": 2, "track_count": 30, "skipped_track_count": 1},
            "previews": {"ran": True, "matched_count": 25, "failed_count": 2},
            "embeddings": {
                "ran": True,
                "model": LOCAL_MUQ_MODEL_NAME,
                "dimensions": LOCAL_MUQ_DIMENSIONS,
                "embedded_count": 23,
                "failed_count": 2,
            },
        }

        response = json_request("GET", f"http://{host}:{port}/status")

        assert response["sync"] == {
            "status": "failed",
            "error": "Could not generate MuQ embedding.",
        }
        assert response["indexing"]["spotify"]["track_count"] == 30
        assert response["indexing"]["embeddings"]["model"] == LOCAL_MUQ_MODEL_NAME
    finally:
        stop_test_server(server, thread)


def test_session_start_claims_active_session() -> None:
    server, thread = start_test_server()

    try:
        host, port = server.server_address
        response = json_request(
            "POST",
            f"http://{host}:{port}/session/start",
            {"session_id": "test-session"},
        )

        assert response["ok"] is False
        assert response["active_session_id"] == "test-session"
        assert response["message"] == "Claude DJ session attached."
        assert response["error_code"] == "insufficient_ready_tracks"
        assert response["catalog"]["needs_onboarding"] is True
        assert response["onboarding"]["index_all_playlists"] is True
    finally:
        stop_test_server(server, thread)


def test_sync_start_runs_one_background_pipeline_at_a_time() -> None:
    calls = []
    release = threading.Event()
    started = threading.Event()

    def fake_indexer() -> IndexSummary:
        calls.append(True)
        started.set()
        release.wait(timeout=2)
        return IndexSummary(
            playlist_count=1,
            track_count=MIN_READY_TRACKS,
            skipped_track_count=0,
            catalog_status=CatalogStatus(
                source_count=1,
                track_count=MIN_READY_TRACKS,
                embedding_count=MIN_READY_TRACKS,
                ready_track_count=MIN_READY_TRACKS,
            ),
        )

    server = create_server(
        catalog_status=CatalogStatus(source_count=1, track_count=0, embedding_count=0),
        spotify_indexer=fake_indexer,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address

        first = json_request("POST", f"http://{host}:{port}/sync/start", {})
        assert started.wait(timeout=2)
        second = json_request("POST", f"http://{host}:{port}/sync/start", {})

        assert first["sync"]["status"] == "running"
        assert second["sync"]["status"] == "running"
        assert calls == [True]
    finally:
        release.set()
        stop_test_server(server, thread)


def test_session_start_with_enough_ready_tracks_starts_sync_without_waiting() -> None:
    calls = []
    release = threading.Event()
    started = threading.Event()

    def fake_indexer() -> IndexSummary:
        calls.append(True)
        started.set()
        release.wait(timeout=2)
        return IndexSummary(
            playlist_count=1,
            track_count=MIN_READY_TRACKS,
            skipped_track_count=0,
            catalog_status=CatalogStatus(
                source_count=1,
                track_count=MIN_READY_TRACKS,
                embedding_count=MIN_READY_TRACKS,
                ready_track_count=MIN_READY_TRACKS,
            ),
        )

    server = create_server(
        catalog_status=CatalogStatus(
            source_count=1,
            track_count=MIN_READY_TRACKS,
            embedding_count=MIN_READY_TRACKS,
            ready_track_count=MIN_READY_TRACKS,
        ),
        spotify_indexer=fake_indexer,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address

        response = json_request(
            "POST",
            f"http://{host}:{port}/session/start",
            {"session_id": "test-session"},
        )

        assert response["ok"] is True
        assert response["catalog"]["ready_track_count"] == MIN_READY_TRACKS
        assert response["sync"]["status"] == "running"
        assert started.wait(timeout=2)
        assert calls == [True]
    finally:
        release.set()
        stop_test_server(server, thread)


def test_session_start_returns_first_recommendation_when_ready() -> None:
    def fake_recommender(recently_played_track_ids: set[int]) -> DJBlock:
        assert recently_played_track_ids == set()
        return DJBlock(
            source_id=10,
            seed_track_id=1,
            tracks=(
                DJTrack(track_id=1, role="seed", distance=None),
                DJTrack(track_id=2, role="similar", distance=0.1),
                DJTrack(track_id=3, role="similar", distance=0.2),
            ),
        )

    server = create_server(
        catalog_status=CatalogStatus(
            source_count=1,
            track_count=MIN_READY_TRACKS,
            embedding_count=MIN_READY_TRACKS,
            ready_track_count=MIN_READY_TRACKS,
        ),
        recommendation_generator=fake_recommender,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address

        response = json_request(
            "POST",
            f"http://{host}:{port}/session/start",
            {"session_id": "test-session"},
        )

        assert response["ok"] is True
        assert response["recommendation"] == {
            "source_id": 10,
            "seed_track_id": 1,
            "tracks": [
                {"track_id": 1, "role": "seed", "distance": None},
                {"track_id": 2, "role": "similar", "distance": 0.1},
                {"track_id": 3, "role": "similar", "distance": 0.2},
            ],
        }
    finally:
        stop_test_server(server, thread)


def test_recommendations_next_uses_in_memory_cooldown() -> None:
    calls = []

    def fake_recommender(recently_played_track_ids: set[int]) -> DJBlock:
        calls.append(set(recently_played_track_ids))
        if not recently_played_track_ids:
            return DJBlock(
                source_id=10,
                seed_track_id=1,
                tracks=(
                    DJTrack(track_id=1, role="seed", distance=None),
                    DJTrack(track_id=2, role="similar", distance=0.1),
                    DJTrack(track_id=3, role="similar", distance=0.2),
                ),
            )
        return DJBlock(
            source_id=11,
            seed_track_id=4,
            tracks=(
                DJTrack(track_id=4, role="seed", distance=None),
                DJTrack(track_id=5, role="similar", distance=0.1),
                DJTrack(track_id=6, role="similar", distance=0.2),
            ),
        )

    server = create_server(
        catalog_status=CatalogStatus(
            source_count=1,
            track_count=MIN_READY_TRACKS,
            embedding_count=MIN_READY_TRACKS,
            ready_track_count=MIN_READY_TRACKS,
        ),
        recommendation_generator=fake_recommender,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address

        first = json_request("POST", f"http://{host}:{port}/recommendations/next", {})
        second = json_request("POST", f"http://{host}:{port}/recommendations/next", {})

        assert first["recommendation"]["seed_track_id"] == 1
        assert second["recommendation"]["seed_track_id"] == 4
        assert calls == [set(), {1, 2, 3}]
    finally:
        stop_test_server(server, thread)


def test_session_start_waits_until_sync_reaches_minimum_ready_tracks() -> None:
    calls = []

    def fake_indexer() -> IndexSummary:
        calls.append(True)
        return IndexSummary(
            playlist_count=1,
            track_count=MIN_READY_TRACKS,
            skipped_track_count=0,
            catalog_status=CatalogStatus(
                source_count=1,
                track_count=MIN_READY_TRACKS,
                embedding_count=MIN_READY_TRACKS,
                ready_track_count=MIN_READY_TRACKS,
            ),
        )

    server = create_server(
        catalog_status=CatalogStatus(
            source_count=1,
            track_count=MIN_READY_TRACKS,
            embedding_count=0,
            ready_track_count=0,
        ),
        spotify_indexer=fake_indexer,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address

        response = json_request(
            "POST",
            f"http://{host}:{port}/session/start",
            {"session_id": "test-session"},
        )

        assert calls == [True]
        assert response["ok"] is True
        assert response["catalog"]["ready_track_count"] == MIN_READY_TRACKS
        assert response["sync"]["status"] in {"running", "completed"}
    finally:
        stop_test_server(server, thread)


def test_session_start_reports_insufficient_library_when_sync_cannot_reach_minimum() -> None:
    def fake_indexer() -> IndexSummary:
        return IndexSummary(
            playlist_count=1,
            track_count=10,
            skipped_track_count=0,
            catalog_status=CatalogStatus(source_count=1, track_count=10, embedding_count=0),
        )

    server = create_server(
        catalog_status=CatalogStatus(source_count=0, track_count=0, embedding_count=0),
        spotify_indexer=fake_indexer,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address

        response = json_request(
            "POST",
            f"http://{host}:{port}/session/start",
            {"session_id": "test-session"},
        )

        assert response["ok"] is False
        assert response["error_code"] == "insufficient_ready_tracks"
        assert response["minimum_ready_tracks"] == MIN_READY_TRACKS
        assert response["catalog"]["track_count"] == 10
    finally:
        stop_test_server(server, thread)


def test_session_start_indexes_spotify_catalog_when_empty() -> None:
    calls = []

    def fake_indexer() -> IndexSummary:
        calls.append(True)
        return IndexSummary(
            playlist_count=2,
            track_count=3,
            skipped_track_count=1,
            catalog_status=CatalogStatus(source_count=2, track_count=3, embedding_count=0),
        )

    server = create_server(
        catalog_status=CatalogStatus(source_count=0, track_count=0, embedding_count=0),
        spotify_indexer=fake_indexer,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address

        response = json_request(
            "POST",
            f"http://{host}:{port}/session/start",
            {"session_id": "test-session"},
        )

        assert calls == [True]
        assert response["catalog"]["source_count"] == 2
        assert response["catalog"]["track_count"] == 3
        assert response["catalog"]["needs_spotify_index"] is False
        assert response["indexing"]["spotify"] == {
            "ran": True,
            "playlist_count": 2,
            "track_count": 3,
            "skipped_track_count": 1,
        }
        assert response["onboarding"]["index_all_playlists"] is False
        assert response["onboarding"]["resolve_previews"] is True
    finally:
        stop_test_server(server, thread)


def test_session_start_resolves_deezer_previews_after_spotify_indexing() -> None:
    calls = []

    def fake_indexer() -> IndexSummary:
        return IndexSummary(
            playlist_count=1,
            track_count=2,
            skipped_track_count=0,
            catalog_status=CatalogStatus(
                source_count=1,
                track_count=2,
                embedding_count=0,
                preview_match_count=0,
                preview_pending_count=2,
            ),
        )

    def fake_preview_resolver() -> PreviewResolutionSummary:
        calls.append(True)
        return PreviewResolutionSummary(
            catalog_status=CatalogStatus(
                source_count=1,
                track_count=2,
                embedding_count=0,
                preview_match_count=2,
                preview_pending_count=0,
                embedding_pending_count=2,
            ),
            matched_count=2,
        )

    server = create_server(
        catalog_status=CatalogStatus(source_count=0, track_count=0, embedding_count=0),
        spotify_indexer=fake_indexer,
        preview_resolver=fake_preview_resolver,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address

        response = json_request(
            "POST",
            f"http://{host}:{port}/session/start",
            {"session_id": "test-session"},
        )

        assert calls == [True]
        assert response["catalog"]["preview_match_count"] == 2
        assert response["catalog"]["preview_pending_count"] == 0
        assert response["indexing"]["previews"] == {
            "ran": True,
            "provider": "deezer",
            "resolved_count": 2,
            "matched_count": 2,
            "no_preview_count": 0,
            "not_found_count": 0,
            "no_isrc_count": 0,
            "rate_limited_count": 0,
            "failed_count": 0,
        }
        assert response["onboarding"]["resolve_previews"] is False
        assert response["onboarding"]["embed_tracks"] is True
    finally:
        stop_test_server(server, thread)


def test_session_start_generates_embeddings_after_preview_resolution() -> None:
    calls = []

    def fake_preview_resolver() -> PreviewResolutionSummary:
        return PreviewResolutionSummary(
            catalog_status=CatalogStatus(
                source_count=1,
                track_count=2,
                embedding_count=0,
                preview_match_count=2,
                preview_pending_count=0,
                embedding_pending_count=2,
            ),
            matched_count=2,
        )

    def fake_embedding_generator() -> EmbeddingGenerationSummary:
        calls.append(True)
        return EmbeddingGenerationSummary(
            catalog_status=CatalogStatus(
                source_count=1,
                track_count=2,
                embedding_count=2,
                preview_match_count=2,
                preview_pending_count=0,
                embedding_pending_count=0,
            ),
            model_name=LOCAL_MUQ_MODEL_NAME,
            dimensions=LOCAL_MUQ_DIMENSIONS,
            embedded_count=2,
        )

    server = create_server(
        catalog_status=CatalogStatus(
            source_count=1,
            track_count=2,
            embedding_count=0,
            preview_match_count=0,
            preview_pending_count=2,
        ),
        preview_resolver=fake_preview_resolver,
        embedding_generator=fake_embedding_generator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address

        response = json_request(
            "POST",
            f"http://{host}:{port}/session/start",
            {"session_id": "test-session"},
        )

        assert calls == [True]
        assert response["catalog"]["embedding_count"] == 2
        assert response["indexing"]["embeddings"] == {
            "ran": True,
            "model": LOCAL_MUQ_MODEL_NAME,
            "dimensions": LOCAL_MUQ_DIMENSIONS,
            "embedded_count": 2,
            "failed_count": 0,
        }
        assert response["onboarding"]["embed_tracks"] is False
    finally:
        stop_test_server(server, thread)


def test_sync_pipeline_resolves_and_embeds_in_chunks() -> None:
    calls = []
    catalog_states = [
        CatalogStatus(
            source_count=1,
            track_count=25,
            embedding_count=0,
            ready_track_count=0,
            preview_match_count=10,
            preview_pending_count=15,
            embedding_pending_count=10,
        ),
        CatalogStatus(
            source_count=1,
            track_count=25,
            embedding_count=10,
            ready_track_count=10,
            preview_match_count=10,
            preview_pending_count=15,
            embedding_pending_count=0,
        ),
        CatalogStatus(
            source_count=1,
            track_count=25,
            embedding_count=10,
            ready_track_count=10,
            preview_match_count=20,
            preview_pending_count=5,
            embedding_pending_count=10,
        ),
        CatalogStatus(
            source_count=1,
            track_count=25,
            embedding_count=20,
            ready_track_count=20,
            preview_match_count=20,
            preview_pending_count=5,
            embedding_pending_count=0,
        ),
        CatalogStatus(
            source_count=1,
            track_count=25,
            embedding_count=20,
            ready_track_count=20,
            preview_match_count=25,
            preview_pending_count=0,
            embedding_pending_count=5,
        ),
        CatalogStatus(
            source_count=1,
            track_count=25,
            embedding_count=25,
            ready_track_count=25,
            preview_match_count=25,
            preview_pending_count=0,
            embedding_pending_count=0,
        ),
    ]

    def fake_preview_resolver() -> PreviewResolutionSummary:
        calls.append("previews")
        return PreviewResolutionSummary(catalog_status=catalog_states.pop(0), matched_count=10 if len(calls) < 5 else 5)

    def fake_embedding_generator() -> EmbeddingGenerationSummary:
        calls.append("embeddings")
        return EmbeddingGenerationSummary(
            catalog_status=catalog_states.pop(0),
            model_name=LOCAL_MUQ_MODEL_NAME,
            dimensions=LOCAL_MUQ_DIMENSIONS,
            embedded_count=10 if len(calls) < 6 else 5,
        )

    server = create_server(
        catalog_status=CatalogStatus(
            source_count=1,
            track_count=25,
            embedding_count=0,
            ready_track_count=0,
            preview_match_count=0,
            preview_pending_count=25,
            embedding_pending_count=0,
        ),
        preview_resolver=fake_preview_resolver,
        embedding_generator=fake_embedding_generator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address

        response = json_request("POST", f"http://{host}:{port}/sync/start", {})
        assert response["sync"]["status"] == "running"

        deadline = threading.Event()
        for _ in range(40):
            status = json_request("GET", f"http://{host}:{port}/status")
            if status["sync"]["status"] == "completed":
                break
            deadline.wait(0.05)

        status = json_request("GET", f"http://{host}:{port}/status")

        assert calls == ["previews", "embeddings", "previews", "embeddings", "previews", "embeddings"]
        assert status["sync"]["status"] == "completed"
        assert status["catalog"]["preview_pending_count"] == 0
        assert status["catalog"]["embedding_count"] == 25
        assert status["indexing"]["previews"]["matched_count"] == 25
        assert status["indexing"]["embeddings"]["embedded_count"] == 25
    finally:
        stop_test_server(server, thread)


def test_sync_pipeline_refreshes_preview_urls_before_embedding_pending_tracks() -> None:
    calls = []

    def fake_preview_resolver() -> PreviewResolutionSummary:
        calls.append("previews")
        return PreviewResolutionSummary(
            catalog_status=CatalogStatus(
                source_count=1,
                track_count=1,
                embedding_count=0,
                ready_track_count=0,
                preview_match_count=1,
                preview_pending_count=0,
                embedding_pending_count=1,
            ),
            matched_count=1,
        )

    def fake_embedding_generator() -> EmbeddingGenerationSummary:
        calls.append("embeddings")
        return EmbeddingGenerationSummary(
            catalog_status=CatalogStatus(
                source_count=1,
                track_count=1,
                embedding_count=1,
                ready_track_count=1,
                preview_match_count=1,
                preview_pending_count=0,
                embedding_pending_count=0,
            ),
            model_name=LOCAL_MUQ_MODEL_NAME,
            dimensions=LOCAL_MUQ_DIMENSIONS,
            embedded_count=1,
        )

    server = create_server(
        catalog_status=CatalogStatus(
            source_count=1,
            track_count=1,
            embedding_count=0,
            ready_track_count=0,
            preview_match_count=1,
            preview_pending_count=0,
            embedding_pending_count=1,
        ),
        preview_resolver=fake_preview_resolver,
        embedding_generator=fake_embedding_generator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address

        json_request("POST", f"http://{host}:{port}/sync/start", {})
        waiter = threading.Event()
        for _ in range(40):
            status = json_request("GET", f"http://{host}:{port}/status")
            if status["sync"]["status"] == "completed":
                break
            waiter.wait(0.05)

        assert calls == ["previews", "embeddings"]
    finally:
        stop_test_server(server, thread)


def test_session_start_refreshes_existing_spotify_catalog() -> None:
    calls = []

    def fake_indexer() -> IndexSummary:
        calls.append(True)
        return IndexSummary(
            playlist_count=1,
            track_count=MIN_READY_TRACKS,
            skipped_track_count=0,
            catalog_status=CatalogStatus(
                source_count=1,
                track_count=MIN_READY_TRACKS,
                embedding_count=MIN_READY_TRACKS,
                ready_track_count=MIN_READY_TRACKS,
            ),
        )

    server = create_server(
        catalog_status=CatalogStatus(source_count=1, track_count=1, embedding_count=0),
        spotify_indexer=fake_indexer,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address

        response = json_request(
            "POST",
            f"http://{host}:{port}/session/start",
            {"session_id": "test-session"},
        )

        assert calls == [True]
        assert response["catalog"]["ready_track_count"] == MIN_READY_TRACKS
        assert response["onboarding"]["index_all_playlists"] is False
    finally:
        stop_test_server(server, thread)


def test_session_start_reports_spotify_auth_needed() -> None:
    def fake_indexer() -> IndexSummary:
        raise SpotifyIndexingAuthRequired("Spotify login is required before playlist indexing.")

    server = create_server(
        catalog_status=CatalogStatus(source_count=0, track_count=0, embedding_count=0),
        spotify_indexer=fake_indexer,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address

        response = json_request(
            "POST",
            f"http://{host}:{port}/session/start",
            {"session_id": "test-session"},
        )

        assert response["indexing"]["spotify"] == {
            "ran": False,
            "error_code": "spotify_auth_required",
            "message": "Spotify login is required before playlist indexing.",
        }
        assert response["onboarding"]["index_all_playlists"] is True
    finally:
        stop_test_server(server, thread)


def test_session_start_reports_spotify_access_denied() -> None:
    def fake_indexer() -> IndexSummary:
        raise SpotifyIndexingAccessDenied("Spotify denied playlist track access.")

    server = create_server(
        catalog_status=CatalogStatus(source_count=0, track_count=0, embedding_count=0),
        spotify_indexer=fake_indexer,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address

        response = json_request(
            "POST",
            f"http://{host}:{port}/session/start",
            {"session_id": "test-session"},
        )

        assert response["indexing"]["spotify"] == {
            "ran": False,
            "error_code": "spotify_access_denied",
            "message": "Spotify denied playlist track access.",
        }
    finally:
        stop_test_server(server, thread)


def test_post_endpoints_require_json() -> None:
    server, thread = start_test_server()

    try:
        host, port = server.server_address
        request = urllib.request.Request(
            f"http://{host}:{port}/session/start",
            data=b"plain text",
            headers={"Content-Type": "text/plain"},
            method="POST",
        )

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request, timeout=2)

        assert exc_info.value.code == 415
    finally:
        stop_test_server(server, thread)


def test_quit_endpoint_stops_server() -> None:
    server, thread = start_test_server()
    host, port = server.server_address

    response = json_request("POST", f"http://{host}:{port}/daemon/quit", {})

    thread.join(timeout=2)
    assert response["ok"] is True
    assert response["message"] == "Claude DJ daemon stopped."
    assert not thread.is_alive()


def test_write_runtime_file_records_daemon_location(tmp_path) -> None:
    runtime_file = tmp_path / "runtime.json"

    write_runtime_file(runtime_file, pid=123, host="127.0.0.1", port=456)

    assert json.loads(runtime_file.read_text()) == {
        "pid": 123,
        "host": "127.0.0.1",
        "port": 456,
    }
