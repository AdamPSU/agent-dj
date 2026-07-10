"""Local daemon HTTP endpoint tests."""

import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from claude_dj.audio.embeddings import EmbeddingGenerationSummary
from claude_dj.audio.previews import PreviewResolutionSummary
from claude_dj.config import LOCAL_MUQ_DIMENSIONS, LOCAL_MUQ_MODEL_NAME, get_embedding_config
from claude_dj.daemon import create_server, write_runtime_file
from claude_dj.indexing import IndexSummary, SpotifyIndexingAccessDenied, SpotifyIndexingAuthRequired
from claude_dj.storage.db import CatalogStatus, connect, initialize_schema, upsert_track, upsert_track_embedding


LEGACY_EMBEDDING_MODEL_NAME = "legacy-audio-model"
LEGACY_EMBEDDING_DIMENSIONS = 512


def start_test_server(**kwargs):
    server = create_server(**kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop_test_server(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    sync_thread = server.state.sync_thread
    if sync_thread is not None and sync_thread.is_alive():
        sync_thread.join(timeout=2)


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


def wait_for_sync(server) -> dict:
    host, port = server.server_address
    waiter = threading.Event()
    for _ in range(40):
        status = json_request("GET", f"http://{host}:{port}/status")
        if status["sync"]["status"] != "running":
            return status
        waiter.wait(0.05)
    raise AssertionError("sync did not finish")


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


def test_server_binds_to_loopback_dynamic_port() -> None:
    server = create_server()
    try:
        host, port = server.server_address
        assert host == "127.0.0.1"
        assert port > 0
    finally:
        server.server_close()


def test_status_endpoint_returns_daemon_and_sync_state() -> None:
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

        assert response["ok"] is True
        assert response["status"] == "running"
        assert response["host"] == "127.0.0.1"
        assert response["pid"] == os.getpid()
        assert response["sync"] == {"status": "failed", "error": "Could not generate MuQ embedding."}
        assert response["indexing"]["spotify"]["track_count"] == 30
        assert "playback" not in response
    finally:
        stop_test_server(server, thread)


def test_session_start_claims_active_session_without_recommendation_fields() -> None:
    server, thread = start_test_server()
    try:
        host, port = server.server_address
        response = json_request(
            "POST",
            f"http://{host}:{port}/session/start",
            {"session_id": "test-session"},
        )

        assert response["ok"] is True
        assert response["active_session_id"] == "test-session"
        assert response["message"] == "Claude DJ session attached."
        assert response["catalog"]["needs_onboarding"] is True
        assert response["onboarding"]["index_all_playlists"] is True
        assert "error_code" not in response
        assert "minimum_ready_tracks" not in response
        assert "recommendation" not in response
        assert "playback" not in response
    finally:
        stop_test_server(server, thread)


def test_session_start_uses_one_catalog_snapshot() -> None:
    server, thread = start_test_server()

    class SwitchingCatalogStatus:
        needs_spotify_index = True
        needs_preview_resolution = True
        needs_embeddings = True

        def to_json(self) -> dict[str, object]:
            server.state.catalog_status = CatalogStatus(
                source_count=1,
                track_count=1,
                embedding_count=1,
                preview_match_count=1,
                preview_pending_count=0,
                embedding_pending_count=0,
            )
            return {"snapshot": "before-sync-update"}

    try:
        server.state.catalog_status = SwitchingCatalogStatus()
        server.state.sync_status = "running"
        host, port = server.server_address

        response = json_request(
            "POST",
            f"http://{host}:{port}/session/start",
            {"session_id": "test-session"},
        )

        assert response["catalog"] == {"snapshot": "before-sync-update"}
        assert response["onboarding"] == {
            "index_all_playlists": True,
            "resolve_previews": True,
            "embed_tracks": True,
        }
    finally:
        stop_test_server(server, thread)


def test_session_start_returns_before_background_sync_finishes() -> None:
    started = threading.Event()
    release = threading.Event()

    def slow_indexer() -> IndexSummary:
        started.set()
        release.wait(timeout=2)
        return IndexSummary(
            playlist_count=1,
            track_count=1,
            skipped_track_count=0,
            catalog_status=CatalogStatus(source_count=1, track_count=1, embedding_count=0),
        )

    server, thread = start_test_server(spotify_indexer=slow_indexer)
    try:
        host, port = server.server_address
        response = json_request("POST", f"http://{host}:{port}/session/start", {"session_id": "test-session"})

        assert response["ok"] is True
        assert response["sync"]["status"] == "running"
        assert started.wait(timeout=1)
        assert server.state.sync_thread is not None
        assert server.state.sync_thread.is_alive()
    finally:
        release.set()
        stop_test_server(server, thread)


def test_repeated_session_start_joins_running_sync() -> None:
    calls = []
    started = threading.Event()
    release = threading.Event()

    def slow_indexer() -> IndexSummary:
        calls.append(True)
        started.set()
        release.wait(timeout=2)
        return IndexSummary(
            playlist_count=1,
            track_count=1,
            skipped_track_count=0,
            catalog_status=CatalogStatus(source_count=1, track_count=1, embedding_count=0),
        )

    server, thread = start_test_server(spotify_indexer=slow_indexer)
    try:
        host, port = server.server_address
        first = json_request("POST", f"http://{host}:{port}/session/start", {"session_id": "first"})
        assert started.wait(timeout=1)
        sync_thread = server.state.sync_thread
        second = json_request("POST", f"http://{host}:{port}/session/start", {"session_id": "second"})

        assert first["sync"]["status"] == "running"
        assert second["sync"]["status"] == "running"
        assert second["active_session_id"] == "second"
        assert server.state.sync_thread is sync_thread
        assert calls == [True]
    finally:
        release.set()
        stop_test_server(server, thread)


def test_recommendations_next_is_not_a_daemon_route() -> None:
    server, thread = start_test_server()
    try:
        host, port = server.server_address
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            json_request("POST", f"http://{host}:{port}/recommendations/next", {})
        assert exc_info.value.code == 404
    finally:
        stop_test_server(server, thread)


def test_sync_start_runs_one_background_pipeline_at_a_time() -> None:
    calls = []
    started = threading.Event()
    release = threading.Event()

    def slow_indexer() -> IndexSummary:
        calls.append(True)
        started.set()
        release.wait(timeout=2)
        return IndexSummary(
            playlist_count=1,
            track_count=1,
            skipped_track_count=0,
            catalog_status=CatalogStatus(source_count=1, track_count=1, embedding_count=0),
        )

    server, thread = start_test_server(spotify_indexer=slow_indexer)
    try:
        host, port = server.server_address
        first = json_request("POST", f"http://{host}:{port}/sync/start", {})
        assert started.wait(timeout=1)
        second = json_request("POST", f"http://{host}:{port}/sync/start", {})

        assert first["sync"]["status"] == "running"
        assert second["sync"]["status"] == "running"
        assert calls == [True]
    finally:
        release.set()
        stop_test_server(server, thread)


def test_sync_pipeline_resolves_and_embeds_in_chunks() -> None:
    calls = []
    catalog_states = [
        CatalogStatus(1, 25, 0, preview_match_count=10, preview_pending_count=15, embedding_pending_count=10),
        CatalogStatus(1, 25, 10, preview_match_count=10, preview_pending_count=15, embedding_pending_count=0),
        CatalogStatus(1, 25, 10, preview_match_count=20, preview_pending_count=5, embedding_pending_count=10),
        CatalogStatus(1, 25, 20, preview_match_count=20, preview_pending_count=5, embedding_pending_count=0),
        CatalogStatus(1, 25, 20, preview_match_count=25, preview_pending_count=0, embedding_pending_count=5),
        CatalogStatus(1, 25, 25, preview_match_count=25, preview_pending_count=0, embedding_pending_count=0),
    ]

    def fake_preview_resolver() -> PreviewResolutionSummary:
        calls.append("previews")
        return PreviewResolutionSummary(
            catalog_status=catalog_states.pop(0),
            matched_count=10 if len(calls) < 5 else 5,
        )

    def fake_embedding_generator() -> EmbeddingGenerationSummary:
        calls.append("embeddings")
        return EmbeddingGenerationSummary(
            catalog_status=catalog_states.pop(0),
            model_name=LOCAL_MUQ_MODEL_NAME,
            dimensions=LOCAL_MUQ_DIMENSIONS,
            embedded_count=10 if len(calls) < 6 else 5,
        )

    server, thread = start_test_server(
        catalog_status=CatalogStatus(
            1,
            25,
            0,
            preview_match_count=0,
            preview_pending_count=25,
            embedding_pending_count=0,
        ),
        preview_resolver=fake_preview_resolver,
        embedding_generator=fake_embedding_generator,
    )
    try:
        host, port = server.server_address
        response = json_request("POST", f"http://{host}:{port}/sync/start", {})
        status = wait_for_sync(server)

        assert response["sync"]["status"] == "running"
        assert calls == ["previews", "embeddings", "previews", "embeddings", "previews", "embeddings"]
        assert status["sync"]["status"] == "completed"
        assert status["catalog"]["preview_pending_count"] == 0
        assert status["catalog"]["embedding_count"] == 25
        assert status["indexing"]["previews"]["matched_count"] == 25
        assert status["indexing"]["embeddings"]["embedded_count"] == 25
    finally:
        stop_test_server(server, thread)


def test_sync_refreshes_preview_before_embedding_pending_tracks() -> None:
    calls = []

    def fake_preview_resolver() -> PreviewResolutionSummary:
        calls.append("previews")
        return PreviewResolutionSummary(
            catalog_status=CatalogStatus(
                1,
                1,
                0,
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
                1,
                1,
                1,
                preview_match_count=1,
                preview_pending_count=0,
                embedding_pending_count=0,
            ),
            model_name=LOCAL_MUQ_MODEL_NAME,
            dimensions=LOCAL_MUQ_DIMENSIONS,
            embedded_count=1,
        )

    server, thread = start_test_server(
        catalog_status=CatalogStatus(
            1,
            1,
            0,
            preview_match_count=1,
            preview_pending_count=0,
            embedding_pending_count=1,
        ),
        preview_resolver=fake_preview_resolver,
        embedding_generator=fake_embedding_generator,
    )
    try:
        host, port = server.server_address
        json_request("POST", f"http://{host}:{port}/sync/start", {})
        status = wait_for_sync(server)

        assert status["sync"]["status"] == "completed"
        assert calls == ["previews", "embeddings"]
    finally:
        stop_test_server(server, thread)


@pytest.mark.parametrize(
    ("error", "error_code", "message"),
    [
        (
            SpotifyIndexingAuthRequired("Spotify login is required before playlist indexing."),
            "spotify_auth_required",
            "Spotify login is required before playlist indexing.",
        ),
        (
            SpotifyIndexingAccessDenied("Spotify denied playlist track access."),
            "spotify_access_denied",
            "Spotify denied playlist track access.",
        ),
    ],
)
def test_sync_reports_spotify_indexing_errors(error, error_code: str, message: str) -> None:
    def failing_indexer() -> IndexSummary:
        raise error

    server, thread = start_test_server(spotify_indexer=failing_indexer)
    try:
        host, port = server.server_address
        json_request("POST", f"http://{host}:{port}/session/start", {"session_id": "test-session"})
        status = wait_for_sync(server)

        assert status["sync"]["status"] == "completed"
        assert status["indexing"]["spotify"] == {
            "ran": False,
            "error_code": error_code,
            "message": message,
        }
    finally:
        stop_test_server(server, thread)


def test_sync_reports_unexpected_failure() -> None:
    def failing_indexer() -> IndexSummary:
        raise RuntimeError("index failed")

    server, thread = start_test_server(spotify_indexer=failing_indexer)
    try:
        host, port = server.server_address
        json_request("POST", f"http://{host}:{port}/sync/start", {})
        status = wait_for_sync(server)

        assert status["sync"] == {"status": "failed", "error": "index failed"}
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
    server.server_close()


def test_write_runtime_file_records_daemon_location(tmp_path) -> None:
    runtime_file = tmp_path / "runtime.json"

    write_runtime_file(runtime_file, pid=123, host="127.0.0.1", port=456)

    assert json.loads(runtime_file.read_text()) == {
        "pid": 123,
        "host": "127.0.0.1",
        "port": 456,
    }
