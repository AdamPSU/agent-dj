"""CLI command parsing and daemon-call behavior tests."""

import io
import os
import threading

from claude_dj import cli
from claude_dj.config import ensure_app_dir, get_runtime_file
from claude_dj.daemon import create_server, write_runtime_file
from claude_dj.indexing import IndexSummary
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


def write_test_runtime(tmp_path, server) -> None:
    app_dir = ensure_app_dir(tmp_path)
    host, port = server.server_address
    write_runtime_file(get_runtime_file(app_dir), pid=os.getpid(), host=host, port=port)


def test_status_reports_not_running_without_runtime(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(tmp_path))
    stdout = io.StringIO()

    exit_code = cli.run(["status"], stdout=stdout)

    assert exit_code == 1
    assert "Claude DJ daemon is not running" in stdout.getvalue()


def test_session_start_timeout_allows_first_embedding_model_load() -> None:
    assert cli.SESSION_START_TIMEOUT_SECONDS >= 600


def test_status_reports_running_daemon(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(tmp_path))
    server, thread = start_test_server()

    try:
        write_test_runtime(tmp_path, server)
        stdout = io.StringIO()

        exit_code = cli.run(["status"], stdout=stdout)

        assert exit_code == 0
        assert "Claude DJ daemon is running" in stdout.getvalue()
    finally:
        stop_test_server(server, thread)


def test_sync_posts_to_sync_start_and_prints_on_device_message(monkeypatch) -> None:
    calls = []
    response = {
        "ok": True,
        "message": "Storing your songs on device.",
        "sync": {"status": "running"},
    }

    def fake_post_json(runtime_info, path, body, timeout_seconds=2):
        calls.append((path, body, timeout_seconds))
        return response

    monkeypatch.setattr(cli, "load_runtime_info", lambda: object())
    monkeypatch.setattr(cli, "is_daemon_running", lambda runtime_info: True)
    monkeypatch.setattr(cli, "post_json", fake_post_json)
    stdout = io.StringIO()

    exit_code = cli.run(["sync"], stdout=stdout)

    assert exit_code == 0
    assert calls == [("/sync/start", {}, 2)]
    assert stdout.getvalue() == "Storing your songs on device.\n"


def test_start_attaches_to_existing_daemon(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(tmp_path))
    server, thread = start_test_server()

    try:
        write_test_runtime(tmp_path, server)
        stdout = io.StringIO()

        exit_code = cli.run(["start"], stdout=stdout)

        assert exit_code == 0
        assert "Claude DJ session attached" in stdout.getvalue()
        assert "Storing your songs on device" in stdout.getvalue()
    finally:
        stop_test_server(server, thread)


def test_start_prints_spotify_indexing_summary(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(tmp_path))

    def fake_indexer() -> IndexSummary:
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
        write_test_runtime(tmp_path, server)
        stdout = io.StringIO()

        exit_code = cli.run(["start"], stdout=stdout)

        assert exit_code == 0
        assert stdout.getvalue() == "Claude DJ session attached.\nStoring your songs on device.\n"
    finally:
        stop_test_server(server, thread)


def test_start_prints_deezer_preview_resolution_summary(monkeypatch) -> None:
    response = {
        "message": "Claude DJ session attached.",
        "catalog": {
            "source_count": 1,
            "track_count": 2,
            "preview_match_count": 2,
            "preview_pending_count": 0,
            "embedding_count": 0,
            "needs_spotify_index": False,
            "needs_preview_resolution": False,
            "needs_embeddings": True,
        },
        "indexing": {
            "spotify": {"ran": False},
            "previews": {
                "ran": True,
                "provider": "deezer",
                "resolved_count": 2,
                "matched_count": 1,
                "no_preview_count": 0,
                "not_found_count": 0,
                "no_isrc_count": 1,
                "rate_limited_count": 0,
                "failed_count": 0,
            },
        },
    }

    monkeypatch.setattr(cli, "load_runtime_info", lambda: object())
    monkeypatch.setattr(cli, "is_daemon_running", lambda runtime_info: True)
    monkeypatch.setattr(cli, "post_json", lambda runtime_info, path, body, **kwargs: response)
    stdout = io.StringIO()

    exit_code = cli.run(["start"], stdout=stdout)

    assert exit_code == 0
    assert stdout.getvalue() == "Claude DJ session attached.\nStoring your songs on device.\n"


def test_start_prints_embedding_generation_summary(monkeypatch) -> None:
    response = {
        "message": "Claude DJ session attached.",
        "catalog": {
            "source_count": 1,
            "track_count": 2,
            "preview_match_count": 2,
            "preview_pending_count": 0,
            "embedding_count": 2,
            "needs_spotify_index": False,
            "needs_preview_resolution": False,
            "needs_embeddings": False,
        },
        "indexing": {
            "spotify": {"ran": False},
            "previews": {"ran": False},
            "embeddings": {
                "ran": True,
                "model": "OpenMuQ/MuQ-MuLan-large",
                "dimensions": 512,
                "embedded_count": 2,
                "failed_count": 1,
            },
        },
    }

    monkeypatch.setattr(cli, "load_runtime_info", lambda: object())
    monkeypatch.setattr(cli, "is_daemon_running", lambda runtime_info: True)
    monkeypatch.setattr(cli, "post_json", lambda runtime_info, path, body, **kwargs: response)
    stdout = io.StringIO()

    exit_code = cli.run(["start"], stdout=stdout)

    assert exit_code == 0
    assert stdout.getvalue() == "Claude DJ session attached.\nStoring your songs on device.\n"


def test_start_prints_spotify_auth_instruction(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(tmp_path))
    response = {
        "message": "Claude DJ session attached.",
        "catalog": {
            "source_count": 0,
            "track_count": 0,
            "embedding_count": 0,
            "needs_spotify_index": True,
        },
        "indexing": {
            "spotify": {
                "ran": False,
                "error_code": "spotify_auth_required",
                "message": "Spotify login is required before playlist indexing.",
            }
        },
    }

    monkeypatch.setattr(cli, "load_runtime_info", lambda: object())
    monkeypatch.setattr(cli, "is_daemon_running", lambda runtime_info: True)
    monkeypatch.setattr(cli, "post_json", lambda runtime_info, path, body, **kwargs: response)
    stdout = io.StringIO()

    exit_code = cli.run(["start"], stdout=stdout)

    assert exit_code == 0
    assert "Spotify login is required before playlist indexing." in stdout.getvalue()
    assert "Run: uv run claude-dj spotify-login" in stdout.getvalue()


def test_start_prints_spotify_access_denied(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(tmp_path))
    response = {
        "message": "Claude DJ session attached.",
        "catalog": {
            "source_count": 0,
            "track_count": 0,
            "embedding_count": 0,
            "needs_spotify_index": True,
        },
        "indexing": {
            "spotify": {
                "ran": False,
                "error_code": "spotify_access_denied",
                "message": "Spotify denied playlist track access.",
            }
        },
    }

    monkeypatch.setattr(cli, "load_runtime_info", lambda: object())
    monkeypatch.setattr(cli, "is_daemon_running", lambda runtime_info: True)
    monkeypatch.setattr(cli, "post_json", lambda runtime_info, path, body, **kwargs: response)
    stdout = io.StringIO()

    exit_code = cli.run(["start"], stdout=stdout)

    assert exit_code == 0
    assert "Spotify denied playlist track access." in stdout.getvalue()
    assert "Run: uv run claude-dj spotify-login" not in stdout.getvalue()
    assert "Indexing all Spotify playlists is needed" not in stdout.getvalue()


def test_start_spawns_daemon_when_none_is_running(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(tmp_path))
    server, thread = start_test_server()
    spawned = []

    def fake_spawn_daemon() -> None:
        spawned.append(True)
        write_test_runtime(tmp_path, server)

    try:
        monkeypatch.setattr(cli, "spawn_daemon", fake_spawn_daemon)
        stdout = io.StringIO()

        exit_code = cli.run(["start"], stdout=stdout)

        assert exit_code == 0
        assert spawned == [True]
        assert "Claude DJ session attached" in stdout.getvalue()
    finally:
        stop_test_server(server, thread)


def test_start_allows_long_running_session_start(monkeypatch) -> None:
    calls = []
    response = {
        "message": "Claude DJ session attached.",
        "catalog": {"needs_spotify_index": False},
        "indexing": {"spotify": {"ran": False}},
    }

    def fake_post_json(runtime_info, path, body, timeout_seconds=2):
        calls.append(timeout_seconds)
        return response

    monkeypatch.setattr(cli, "load_runtime_info", lambda: object())
    monkeypatch.setattr(cli, "is_daemon_running", lambda runtime_info: True)
    monkeypatch.setattr(cli, "post_json", fake_post_json)
    stdout = io.StringIO()

    exit_code = cli.run(["start"], stdout=stdout)

    assert exit_code == 0
    assert calls == [cli.SESSION_START_TIMEOUT_SECONDS]


def test_quit_stops_running_daemon(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(tmp_path))
    server, thread = start_test_server()
    write_test_runtime(tmp_path, server)
    stdout = io.StringIO()

    exit_code = cli.run(["quit"], stdout=stdout)

    thread.join(timeout=2)
    assert exit_code == 0
    assert "Claude DJ daemon stopped" in stdout.getvalue()
    assert not thread.is_alive()


def test_spotify_login_runs_auth_flow(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(tmp_path))
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client-id")
    calls = []

    def fake_perform_spotify_login(config, token_file):
        calls.append((config, token_file))

    monkeypatch.setattr(cli, "perform_spotify_login", fake_perform_spotify_login)
    stdout = io.StringIO()

    exit_code = cli.run(["spotify-login"], stdout=stdout)

    assert exit_code == 0
    assert calls[0][0].client_id == "client-id"
    assert calls[0][1] == tmp_path / "spotify-token.json"
    assert "Spotify login complete" in stdout.getvalue()
