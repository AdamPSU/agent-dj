"""CLI command parsing and daemon-call behavior tests."""

import io
import http.client
import os
import threading

from claude_dj import cli
from claude_dj.adapters.spotify import SpotifyDevice
from claude_dj.config import ensure_app_dir, get_runtime_file
from claude_dj.daemon import create_server, write_runtime_file
from claude_dj.devices import DevicePreference
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


def test_status_prints_catalog_sync_and_last_run_details(monkeypatch) -> None:
    response = {
        "host": "127.0.0.1",
        "port": 63964,
        "sync": {"status": "failed", "error": "Could not generate MuQ embedding."},
        "catalog": {
            "source_count": 25,
            "track_count": 1838,
            "preview_match_count": 67,
            "preview_pending_count": 1771,
            "embedding_count": 65,
            "ready_track_count": 65,
            "embedding_pending_count": 0,
            "needs_onboarding": True,
            "ready_for_audio_similarity": True,
        },
        "indexing": {
            "spotify": {"ran": True, "playlist_count": 25, "track_count": 1838, "skipped_track_count": 3},
            "previews": {"ran": True, "matched_count": 65, "failed_count": 2},
            "embeddings": {
                "ran": True,
                "model": "OpenMuQ/MuQ-large-msd-iter",
                "dimensions": 1024,
                "embedded_count": 65,
                "failed_count": 0,
            },
        },
    }

    monkeypatch.setattr(cli, "load_runtime_info", lambda: object())
    monkeypatch.setattr(cli, "is_daemon_running", lambda runtime_info: True)
    monkeypatch.setattr(cli, "get_json", lambda runtime_info, path: response)
    stdout = io.StringIO()

    exit_code = cli.run(["status"], stdout=stdout)

    assert exit_code == 0
    assert stdout.getvalue() == (
        "Claude DJ daemon is running on 127.0.0.1:63964.\n"
        "\n"
        "Sync: failed\n"
        "Error: Could not generate MuQ embedding.\n"
        "Catalog:\n"
        "  Playlists: 25\n"
        "  Tracks: 1838\n"
        "  Previews: 67 matched, 1771 pending\n"
        "  Embeddings: 65 ready, 0 pending\n"
        "  Model: OpenMuQ/MuQ-large-msd-iter, 1024 dimensions\n"
        "\n"
        "Readiness:\n"
        "  Ready tracks: 65\n"
        "  Audio similarity: ready\n"
        "  Onboarding: still loading songs\n"
        "\n"
        "Last run:\n"
        "  Spotify: indexed 25 playlists, 1838 tracks, skipped 3\n"
        "  Previews: matched 65, failed 2\n"
        "  Embeddings: embedded 65, failed 0\n"
    )


def test_status_prints_playback_monitor_details(monkeypatch) -> None:
    response = {
        "host": "127.0.0.1",
        "port": 63964,
        "playback": {
            "status": "failed",
            "known_track_count": 2,
            "error": "Spotify denied playback control.",
        },
    }

    monkeypatch.setattr(cli, "load_runtime_info", lambda: object())
    monkeypatch.setattr(cli, "is_daemon_running", lambda runtime_info: True)
    monkeypatch.setattr(cli, "get_json", lambda runtime_info, path: response)
    stdout = io.StringIO()

    exit_code = cli.run(["status"], stdout=stdout)

    assert exit_code == 0
    assert stdout.getvalue() == (
        "Claude DJ daemon is running on 127.0.0.1:63964.\n"
        "\n"
        "Playback:\n"
        "  Monitor: failed\n"
        "  Known queue tracks: 2\n"
        "  Error: Spotify denied playback control.\n"
    )


def test_status_reports_still_loading_when_previews_are_pending(monkeypatch) -> None:
    response = {
        "host": "127.0.0.1",
        "port": 63964,
        "catalog": {
            "source_count": 25,
            "track_count": 1838,
            "preview_match_count": 67,
            "preview_pending_count": 1771,
            "embedding_count": 65,
            "ready_track_count": 65,
            "embedding_pending_count": 0,
            "needs_onboarding": False,
            "ready_for_audio_similarity": True,
        },
    }

    monkeypatch.setattr(cli, "load_runtime_info", lambda: object())
    monkeypatch.setattr(cli, "is_daemon_running", lambda runtime_info: True)
    monkeypatch.setattr(cli, "get_json", lambda runtime_info, path: response)
    stdout = io.StringIO()

    exit_code = cli.run(["status"], stdout=stdout)

    assert exit_code == 0
    assert "Onboarding: still loading songs" in stdout.getvalue()


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


def test_start_retries_when_daemon_disconnects_after_status_check(monkeypatch) -> None:
    response = {
        "message": "Claude DJ session attached.",
        "indexing": {"spotify": {"ran": False}},
    }
    old_runtime = object()
    new_runtime = object()
    post_calls = []
    spawn_calls = []

    def fake_post_json(runtime_info, path, body, **kwargs):
        post_calls.append(runtime_info)
        if len(post_calls) == 1:
            raise http.client.RemoteDisconnected("Remote end closed connection without response")
        return response

    monkeypatch.setattr(cli, "load_runtime_info", lambda: old_runtime)
    monkeypatch.setattr(cli, "is_daemon_running", lambda runtime_info: True)
    monkeypatch.setattr(cli, "post_json", fake_post_json)
    monkeypatch.setattr(cli, "spawn_daemon", lambda: spawn_calls.append(True))
    monkeypatch.setattr(cli, "wait_for_daemon", lambda: new_runtime)
    stdout = io.StringIO()

    exit_code = cli.run(["start"], stdout=stdout)

    assert exit_code == 0
    assert spawn_calls == [True]
    assert post_calls == [old_runtime, new_runtime]
    assert stdout.getvalue() == "Claude DJ session attached.\nStoring your songs on device.\n"


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
                "model": "OpenMuQ/MuQ-large-msd-iter",
                "dimensions": 1024,
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


def test_start_prints_playback_success(monkeypatch) -> None:
    response = {
        "message": "Claude DJ session attached.",
        "indexing": {"spotify": {"ran": False}},
        "playback": {
            "started": True,
            "track_count": 3,
            "first_track": {
                "track_id": 1,
                "title": "Track One",
                "artist_name": "Artist One",
                "spotify_uri": "spotify:track:1",
            },
        },
    }

    monkeypatch.setattr(cli, "load_runtime_info", lambda: object())
    monkeypatch.setattr(cli, "is_daemon_running", lambda runtime_info: True)
    monkeypatch.setattr(cli, "post_json", lambda runtime_info, path, body, **kwargs: response)
    stdout = io.StringIO()

    exit_code = cli.run(["start"], stdout=stdout)

    assert exit_code == 0
    assert stdout.getvalue() == (
        "Claude DJ session attached.\n"
        "Started Claude DJ block: Track One by Artist One + 2 more.\n"
    )


def test_start_prints_targeted_playback_device(monkeypatch) -> None:
    response = {
        "message": "Claude DJ session attached.",
        "indexing": {"spotify": {"ran": False}},
        "playback": {
            "started": True,
            "track_count": 1,
            "first_track": {
                "title": "Track One",
                "artist_name": "Artist One",
            },
            "device": {
                "name": "MacBook",
                "type": "Computer",
            },
            "device_fallback": True,
            "preferred_device_unavailable": False,
        },
    }

    monkeypatch.setattr(cli, "load_runtime_info", lambda: object())
    monkeypatch.setattr(cli, "is_daemon_running", lambda runtime_info: True)
    monkeypatch.setattr(cli, "post_json", lambda runtime_info, path, body, **kwargs: response)
    stdout = io.StringIO()

    exit_code = cli.run(["start"], stdout=stdout)

    assert exit_code == 0
    assert stdout.getvalue() == (
        "Claude DJ session attached.\n"
        "Started Claude DJ block: Track One by Artist One on MacBook.\n"
    )


def test_start_prints_playback_failure(monkeypatch) -> None:
    response = {
        "message": "Claude DJ session attached.",
        "indexing": {"spotify": {"ran": False}},
        "playback": {
            "started": False,
            "error_code": "spotify_no_active_device",
            "message": "No active Spotify device found. Open Spotify on a device, then run /dj start again.",
        },
    }

    monkeypatch.setattr(cli, "load_runtime_info", lambda: object())
    monkeypatch.setattr(cli, "is_daemon_running", lambda runtime_info: True)
    monkeypatch.setattr(cli, "post_json", lambda runtime_info, path, body, **kwargs: response)
    stdout = io.StringIO()

    exit_code = cli.run(["start"], stdout=stdout)

    assert exit_code == 0
    assert stdout.getvalue() == (
        "Claude DJ session attached.\n"
        "No active Spotify device found. Open Spotify on a device, then run /dj start again.\n"
    )


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
    assert "Run: /dj spotify-login" in stdout.getvalue()


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
    assert "Run: /dj spotify-login" not in stdout.getvalue()
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


def test_quit_is_successful_when_daemon_is_not_running(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(tmp_path))
    stdout = io.StringIO()

    exit_code = cli.run(["quit"], stdout=stdout)

    assert exit_code == 0
    assert "Claude DJ daemon is not running" in stdout.getvalue()


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


def test_devices_lists_available_spotify_devices(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(tmp_path))
    monkeypatch.setattr(
        cli,
        "fetch_available_devices_with_token",
        lambda token_file: [
            SpotifyDevice(
                id="device-1",
                name="MacBook",
                type="Computer",
                is_active=False,
                is_restricted=False,
            ),
            SpotifyDevice(
                id="device-2",
                name="Living Room",
                type="Speaker",
                is_active=True,
                is_restricted=False,
            ),
        ],
    )
    monkeypatch.setattr(cli, "load_device_preference", lambda device_file: DevicePreference("device-1", "MacBook", "Computer"))
    stdout = io.StringIO()

    exit_code = cli.run(["devices"], stdout=stdout)

    assert exit_code == 0
    assert stdout.getvalue() == (
        "Spotify devices:\n"
        "  1. MacBook [Computer] available selected\n"
        "  2. Living Room [Speaker] active\n"
    )


def test_device_selects_numbered_spotify_device(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(tmp_path))
    saved = []
    devices = [
        SpotifyDevice(
            id="device-1",
            name="MacBook",
            type="Computer",
            is_active=False,
            is_restricted=False,
        ),
        SpotifyDevice(
            id="device-2",
            name="Living Room",
            type="Speaker",
            is_active=True,
            is_restricted=False,
        ),
    ]
    monkeypatch.setattr(cli, "fetch_available_devices_with_token", lambda token_file: devices)
    monkeypatch.setattr(cli, "save_device_preference", lambda device_file, device: saved.append((device_file, device)))
    stdout = io.StringIO()

    exit_code = cli.run(["device", "2"], stdout=stdout)

    assert exit_code == 0
    assert saved == [(tmp_path / "spotify-device.json", devices[1])]
    assert stdout.getvalue() == "Claude DJ playback device set to Living Room.\n"


def test_device_rejects_out_of_range_selection(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(tmp_path))
    monkeypatch.setattr(
        cli,
        "fetch_available_devices_with_token",
        lambda token_file: [
            SpotifyDevice(
                id="device-1",
                name="MacBook",
                type="Computer",
                is_active=False,
                is_restricted=False,
            )
        ],
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = cli.run(["device", "2"], stdout=stdout, stderr=stderr)

    assert exit_code == 1
    assert stdout.getvalue() == "Choose a device from /dj devices.\n"
