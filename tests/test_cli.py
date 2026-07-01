"""CLI command parsing and daemon-call behavior tests."""

import io
import os
import threading

from claude_dj import cli
from claude_dj.config import ensure_app_dir, get_runtime_file
from claude_dj.daemon import create_server, write_runtime_file


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


def test_start_attaches_to_existing_daemon(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAUDE_DJ_HOME", str(tmp_path))
    server, thread = start_test_server()

    try:
        write_test_runtime(tmp_path, server)
        stdout = io.StringIO()

        exit_code = cli.run(["start"], stdout=stdout)

        assert exit_code == 0
        assert "Claude DJ session attached" in stdout.getvalue()
        assert "Indexing all Spotify playlists is needed" in stdout.getvalue()
    finally:
        stop_test_server(server, thread)


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
