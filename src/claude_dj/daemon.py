"""Long-running local process for Claude DJ.

This module will own session lifecycle, command handling, and the DJ loop.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections.abc import Callable
import json
import os
import threading

from claude_dj.config import ensure_app_dir, get_database_file, get_runtime_file, get_spotify_token_file
from claude_dj.audio.previews import (
    DEEZER_RATE_LIMIT_REQUESTS,
    PreviewResolutionSummary,
    resolve_deezer_previews,
)
from claude_dj.indexing import (
    IndexSummary,
    SpotifyIndexingAccessDenied,
    SpotifyIndexingAuthRequired,
    index_spotify_playlists,
)
from claude_dj.models import RuntimeInfo
from claude_dj.storage.db import CatalogStatus, connect, get_catalog_status, initialize_schema


LOOPBACK_HOST = "127.0.0.1"
PREVIEW_RESOLUTION_BATCH_SIZE = DEEZER_RATE_LIMIT_REQUESTS


SpotifyIndexer = Callable[[], IndexSummary]
PreviewResolver = Callable[[], PreviewResolutionSummary]


class DaemonState:
    """In-memory daemon state for the local control server."""

    def __init__(
        self,
        host: str,
        port: int,
        catalog_status: CatalogStatus,
        spotify_indexer: SpotifyIndexer | None,
        preview_resolver: PreviewResolver | None,
    ) -> None:
        self.host = host
        self.port = port
        self.pid = os.getpid()
        self.active_session_id: str | None = None
        self.catalog_status = catalog_status
        self.spotify_indexer = spotify_indexer
        self.preview_resolver = preview_resolver


class ClaudeDJHTTPServer(ThreadingHTTPServer):
    """HTTP server carrying Claude DJ daemon state."""

    state: DaemonState


class DaemonRequestHandler(BaseHTTPRequestHandler):
    """Local JSON API for Claude DJ CLI commands."""

    server: ClaudeDJHTTPServer

    def do_GET(self) -> None:
        if self.path != "/status":
            self.send_error(404)
            return

        self._send_json(
            200,
            {
                "ok": True,
                "status": "running",
                "pid": self.server.state.pid,
                "host": self.server.state.host,
                "port": self.server.state.port,
                "active_session_id": self.server.state.active_session_id,
                "catalog": self.server.state.catalog_status.to_json(),
            },
        )

    def do_POST(self) -> None:
        if self.headers.get("Content-Type") != "application/json":
            self._send_json(415, {"ok": False, "error": "POST requests require JSON."})
            return

        body = self._read_json_body()
        if body is None:
            self._send_json(400, {"ok": False, "error": "Invalid JSON body."})
            return

        if self.path == "/session/start":
            self._handle_session_start(body)
            return

        if self.path == "/daemon/quit":
            self._send_json(200, {"ok": True, "message": "Claude DJ daemon stopped."})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        """Silence default HTTP request logging for CLI use."""

    def _handle_session_start(self, body: dict[str, object]) -> None:
        session_id = str(body.get("session_id") or "local-cli")
        self.server.state.active_session_id = session_id
        spotify_indexing = self._maybe_index_spotify_catalog()
        preview_resolution = self._maybe_resolve_deezer_previews()
        self._send_json(
            200,
            {
                "ok": True,
                "message": "Claude DJ session attached.",
                "active_session_id": self.server.state.active_session_id,
                "catalog": self.server.state.catalog_status.to_json(),
                "indexing": {"spotify": spotify_indexing, "previews": preview_resolution},
                "onboarding": {
                    "index_all_playlists": self.server.state.catalog_status.needs_spotify_index,
                    "resolve_previews": self.server.state.catalog_status.needs_preview_resolution,
                    "embed_tracks": self.server.state.catalog_status.needs_embeddings,
                },
            },
        )

    def _maybe_index_spotify_catalog(self) -> dict[str, object]:
        if not self.server.state.catalog_status.needs_spotify_index:
            return {"ran": False}
        if self.server.state.spotify_indexer is None:
            return {"ran": False}

        try:
            summary = self.server.state.spotify_indexer()
        except SpotifyIndexingAuthRequired as exc:
            return {
                "ran": False,
                "error_code": "spotify_auth_required",
                "message": str(exc),
            }
        except SpotifyIndexingAccessDenied as exc:
            return {
                "ran": False,
                "error_code": "spotify_access_denied",
                "message": str(exc),
            }

        self.server.state.catalog_status = summary.catalog_status
        return summary.to_json()

    def _maybe_resolve_deezer_previews(self) -> dict[str, object]:
        if not self.server.state.catalog_status.needs_preview_resolution:
            return {"ran": False}
        if self.server.state.preview_resolver is None:
            return {"ran": False}

        summary = self.server.state.preview_resolver()
        self.server.state.catalog_status = summary.catalog_status
        return summary.to_json()

    def _read_json_body(self) -> dict[str, object] | None:
        length = int(self.headers.get("Content-Length") or "0")
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            parsed = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        response = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(response)


def create_server(
    host: str = LOOPBACK_HOST,
    port: int = 0,
    catalog_status: CatalogStatus | None = None,
    spotify_indexer: SpotifyIndexer | None = None,
    preview_resolver: PreviewResolver | None = None,
) -> ClaudeDJHTTPServer:
    """Create a loopback-only local HTTP daemon server."""
    server = ClaudeDJHTTPServer((host, port), DaemonRequestHandler)
    bound_host, bound_port = server.server_address
    server.state = DaemonState(
        host=bound_host,
        port=bound_port,
        catalog_status=catalog_status or CatalogStatus(0, 0, 0),
        spotify_indexer=spotify_indexer,
        preview_resolver=preview_resolver,
    )
    return server


def write_runtime_file(runtime_file: Path, pid: int, host: str, port: int) -> None:
    """Record the daemon process and dynamic port for future CLI commands."""
    runtime_info = RuntimeInfo(pid=pid, host=host, port=port)
    runtime_file.write_text(json.dumps(runtime_info.to_json()), encoding="utf-8")


def run_daemon() -> int:
    """Run the Claude DJ daemon until it is asked to quit."""
    app_dir = ensure_app_dir()
    runtime_file = get_runtime_file(app_dir)
    database_file = get_database_file(app_dir)
    db = connect(database_file)
    initialize_schema(db)
    catalog_status = get_catalog_status(db)
    db.close()

    def spotify_indexer() -> IndexSummary:
        index_db = connect(database_file)
        try:
            initialize_schema(index_db)
            return index_spotify_playlists(
                index_db,
                token_file=get_spotify_token_file(app_dir),
            )
        finally:
            index_db.close()

    def preview_resolver() -> PreviewResolutionSummary:
        preview_db = connect(database_file)
        try:
            initialize_schema(preview_db)
            return resolve_deezer_previews(
                preview_db,
                max_tracks=PREVIEW_RESOLUTION_BATCH_SIZE,
            )
        finally:
            preview_db.close()

    server = create_server(
        catalog_status=catalog_status,
        spotify_indexer=spotify_indexer,
        preview_resolver=preview_resolver,
    )
    host, port = server.server_address
    write_runtime_file(runtime_file, pid=os.getpid(), host=host, port=port)

    try:
        server.serve_forever()
    finally:
        server.server_close()
        _remove_runtime_file(runtime_file)

    return 0


def _remove_runtime_file(runtime_file: Path) -> None:
    try:
        runtime_file.unlink()
    except FileNotFoundError:
        pass


def main() -> int:
    """Daemon module entrypoint."""
    return run_daemon()


if __name__ == "__main__":
    raise SystemExit(main())
