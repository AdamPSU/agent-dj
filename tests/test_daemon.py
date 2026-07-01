"""Local daemon HTTP endpoint tests."""

import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from claude_dj.daemon import create_server, write_runtime_file
from claude_dj.indexing import (
    IndexSummary,
    SpotifyIndexingAccessDenied,
    SpotifyIndexingAuthRequired,
)
from claude_dj.storage.db import CatalogStatus


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


def test_session_start_claims_active_session() -> None:
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


def test_session_start_does_not_reindex_existing_spotify_catalog() -> None:
    calls = []

    def fake_indexer() -> IndexSummary:
        calls.append(True)
        raise AssertionError("should not index")

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

        assert calls == []
        assert response["indexing"]["spotify"] == {"ran": False}
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
