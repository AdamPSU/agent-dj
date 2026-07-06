"""Long-running local process for Claude DJ.

This module will own session lifecycle, command handling, and the DJ loop.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import json
import os
import threading

from claude_dj.config import (
    ensure_app_dir,
    get_database_file,
    get_embedding_config,
    get_runtime_file,
    get_spotify_token_file,
)
from claude_dj.audio.embeddings import EmbeddingGenerationSummary, generate_audio_embeddings
from claude_dj.audio.previews import (
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
from claude_dj.recommendation.similarity import DJBlock, generate_next_dj_block
from claude_dj.storage.db import CatalogStatus, connect, get_catalog_status, initialize_schema


LOOPBACK_HOST = "127.0.0.1"
MIN_READY_TRACKS = 30
SYNC_CHUNK_SIZE = 10
TRACK_COOLDOWN = timedelta(hours=3)


SpotifyIndexer = Callable[[], IndexSummary]
PreviewResolver = Callable[[], PreviewResolutionSummary]
EmbeddingGenerator = Callable[[], EmbeddingGenerationSummary]
CatalogStepRunner = Callable[[], PreviewResolutionSummary | EmbeddingGenerationSummary]
RecommendationGenerator = Callable[[set[int]], DJBlock | None]


class DaemonState:
    """In-memory daemon state for the local control server."""

    def __init__(
        self,
        host: str,
        port: int,
        catalog_status: CatalogStatus,
        spotify_indexer: SpotifyIndexer | None,
        preview_resolver: PreviewResolver | None,
        embedding_generator: EmbeddingGenerator | None,
        recommendation_generator: RecommendationGenerator | None,
    ) -> None:
        self.host = host
        self.port = port
        self.pid = os.getpid()
        self.active_session_id: str | None = None
        self.catalog_status = catalog_status
        self.spotify_indexer = spotify_indexer
        self.preview_resolver = preview_resolver
        self.embedding_generator = embedding_generator
        self.recommendation_generator = recommendation_generator
        self.track_last_played_at: dict[int, datetime] = {}
        self.sync_status = "idle"
        self.sync_error: str | None = None
        self.sync_indexing: dict[str, dict[str, object]] = _empty_indexing_payload()
        self.sync_thread: threading.Thread | None = None
        self.sync_condition = threading.Condition(threading.RLock())


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
                "sync": self._sync_status_json(),
                "indexing": self.server.state.sync_indexing,
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

        if self.path == "/sync/start":
            self._handle_sync_start()
            return

        if self.path == "/recommendations/next":
            self._handle_recommendations_next()
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
        self._start_sync_if_idle()
        self._wait_for_ready_tracks_or_sync_terminal()
        ready = self.server.state.catalog_status.ready_track_count >= MIN_READY_TRACKS
        has_recommendation_generator = self.server.state.recommendation_generator is not None
        recommendation = self._generate_recommendation() if ready and has_recommendation_generator else None
        self._send_json(
            200,
            {
                "ok": ready and (recommendation is not None or not has_recommendation_generator),
                "message": "Claude DJ session attached.",
                "active_session_id": self.server.state.active_session_id,
                "error_code": _session_start_error_code(
                    ready,
                    recommendation,
                    has_recommendation_generator=has_recommendation_generator,
                ),
                "minimum_ready_tracks": MIN_READY_TRACKS,
                "catalog": self.server.state.catalog_status.to_json(),
                "indexing": self.server.state.sync_indexing,
                "onboarding": {
                    "index_all_playlists": self.server.state.catalog_status.needs_spotify_index,
                    "resolve_previews": self.server.state.catalog_status.needs_preview_resolution,
                    "embed_tracks": self.server.state.catalog_status.needs_embeddings,
                },
                "sync": self._sync_status_json(),
                "recommendation": recommendation.to_json() if recommendation is not None else None,
            },
        )

    def _handle_sync_start(self) -> None:
        self._start_sync_if_idle()
        self._send_json(
            200,
            {
                "ok": True,
                "message": "Storing your songs on device.",
                "catalog": self.server.state.catalog_status.to_json(),
                "sync": self._sync_status_json(),
            },
        )

    def _handle_recommendations_next(self) -> None:
        if self.server.state.catalog_status.ready_track_count < MIN_READY_TRACKS:
            self._send_json(
                200,
                {
                    "ok": False,
                    "error_code": "insufficient_ready_tracks",
                    "minimum_ready_tracks": MIN_READY_TRACKS,
                    "catalog": self.server.state.catalog_status.to_json(),
                },
            )
            return

        recommendation = self._generate_recommendation()
        self._send_json(
            200,
            {
                "ok": recommendation is not None,
                "error_code": None if recommendation is not None else "no_recommendation_available",
                "recommendation": recommendation.to_json() if recommendation is not None else None,
            },
        )

    def _run_spotify_indexing(self) -> dict[str, object]:
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

    def _generate_audio_embeddings(self) -> dict[str, object]:
        return self._run_catalog_step_if_needed(
            self.server.state.catalog_status.needs_embeddings,
            self.server.state.embedding_generator,
        )

    def _resolve_deezer_previews(self) -> dict[str, object]:
        if self.server.state.preview_resolver is None:
            return {"ran": False}

        summary = self.server.state.preview_resolver()
        self.server.state.catalog_status = summary.catalog_status
        return summary.to_json()

    def _run_catalog_step_if_needed(
        self,
        needed: bool,
        runner: CatalogStepRunner | None,
    ) -> dict[str, object]:
        if not needed or runner is None:
            return {"ran": False}

        summary = runner()
        self.server.state.catalog_status = summary.catalog_status
        return summary.to_json()

    def _start_sync_if_idle(self) -> dict[str, object]:
        with self.server.state.sync_condition:
            if self.server.state.sync_status == "running":
                return self._sync_status_json()

            self.server.state.sync_status = "running"
            self.server.state.sync_error = None
            self.server.state.sync_indexing = _empty_indexing_payload()
            thread = threading.Thread(target=self._run_sync_pipeline, daemon=True)
            self.server.state.sync_thread = thread
            thread.start()
            self.server.state.sync_condition.notify_all()
            return self._sync_status_json()

    def _run_sync_pipeline(self) -> None:
        indexing = _empty_indexing_payload()
        status = "completed"
        error: str | None = None
        try:
            indexing["spotify"] = self._run_spotify_indexing()
            with self.server.state.sync_condition:
                self.server.state.sync_indexing = indexing
                self.server.state.sync_condition.notify_all()
            indexing["previews"], indexing["embeddings"] = self._run_catalog_chunks(indexing["spotify"])
        except Exception as exc:
            status = "failed"
            error = str(exc)

        with self.server.state.sync_condition:
            self.server.state.sync_status = status
            self.server.state.sync_error = error
            self.server.state.sync_indexing = indexing
            self.server.state.sync_condition.notify_all()

    def _run_catalog_chunks(
        self,
        spotify_indexing: dict[str, object],
    ) -> tuple[dict[str, object], dict[str, object]]:
        previews = _empty_indexing_payload()["previews"]
        embeddings = _empty_indexing_payload()["embeddings"]

        while (
            self.server.state.catalog_status.needs_preview_resolution
            or self.server.state.catalog_status.needs_embeddings
        ):
            progressed = False

            if (
                self.server.state.catalog_status.needs_preview_resolution
                or (
                    self.server.state.catalog_status.needs_embeddings
                    and self.server.state.embedding_generator is not None
                )
            ):
                preview_summary = self._resolve_deezer_previews()
                previews = _merge_preview_indexing(previews, preview_summary)
                progressed = _preview_progressed(preview_summary)
                if preview_summary.get("error_code") == "deezer_rate_limited":
                    break

            if self.server.state.catalog_status.needs_embeddings:
                embedding_summary = self._generate_audio_embeddings()
                embeddings = _merge_embedding_indexing(embeddings, embedding_summary)
                progressed = _embedding_progressed(embedding_summary) or progressed

            with self.server.state.sync_condition:
                self.server.state.sync_indexing = {
                    "spotify": spotify_indexing,
                    "previews": previews,
                    "embeddings": embeddings,
                }
                self.server.state.sync_condition.notify_all()

            if not progressed:
                break

        return previews, embeddings

    def _wait_for_ready_tracks_or_sync_terminal(self) -> None:
        while self.server.state.catalog_status.ready_track_count < MIN_READY_TRACKS:
            with self.server.state.sync_condition:
                if self._cannot_reach_min_ready_tracks():
                    return
                if self.server.state.sync_status != "running":
                    self._start_sync_if_idle()
                self.server.state.sync_condition.wait(timeout=0.05)

    def _cannot_reach_min_ready_tracks(self) -> bool:
        catalog = self.server.state.catalog_status
        potential_ready_count = (
            catalog.ready_track_count
            + catalog._preview_pending_count()
            + catalog._embedding_pending_count()
        )
        return self.server.state.sync_status != "running" and potential_ready_count < MIN_READY_TRACKS

    def _sync_status_json(self) -> dict[str, object]:
        payload: dict[str, object] = {"status": self.server.state.sync_status}
        if self.server.state.sync_error is not None:
            payload["error"] = self.server.state.sync_error
        return payload

    def _generate_recommendation(self) -> DJBlock | None:
        generator = self.server.state.recommendation_generator
        if generator is None:
            return None

        now = datetime.now(UTC)
        with self.server.state.sync_condition:
            recently_played = {
                track_id
                for track_id, played_at in self.server.state.track_last_played_at.items()
                if now - played_at < TRACK_COOLDOWN
            }
            recommendation = generator(recently_played)
            if recommendation is not None:
                for track in recommendation.tracks:
                    self.server.state.track_last_played_at[track.track_id] = now
            return recommendation

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
    embedding_generator: EmbeddingGenerator | None = None,
    recommendation_generator: RecommendationGenerator | None = None,
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
        embedding_generator=embedding_generator,
        recommendation_generator=recommendation_generator,
    )
    return server


def write_runtime_file(runtime_file: Path, pid: int, host: str, port: int) -> None:
    """Record the daemon process and dynamic port for future CLI commands."""
    runtime_info = RuntimeInfo(pid=pid, host=host, port=port)
    runtime_file.write_text(json.dumps(runtime_info.to_json()), encoding="utf-8")


def _empty_indexing_payload() -> dict[str, dict[str, object]]:
    return {
        "spotify": {"ran": False},
        "previews": {"ran": False},
        "embeddings": {"ran": False},
    }


def _merge_preview_indexing(current: dict[str, object], update: dict[str, object]) -> dict[str, object]:
    merged = dict(current)
    count_keys = (
        "resolved_count",
        "matched_count",
        "no_preview_count",
        "not_found_count",
        "no_isrc_count",
        "rate_limited_count",
        "failed_count",
    )
    merged["ran"] = bool(merged.get("ran")) or bool(update.get("ran"))
    for key in count_keys:
        merged[key] = _int_payload_value(merged, key) + _int_payload_value(update, key)
    for key in ("provider", "error_code"):
        value = update.get(key)
        if isinstance(value, str):
            merged[key] = value
    return merged


def _merge_embedding_indexing(current: dict[str, object], update: dict[str, object]) -> dict[str, object]:
    merged = dict(current)
    merged["ran"] = bool(merged.get("ran")) or bool(update.get("ran"))
    for key in ("embedded_count", "failed_count"):
        merged[key] = _int_payload_value(merged, key) + _int_payload_value(update, key)
    for key in ("model", "dimensions", "timing"):
        if key in update:
            merged[key] = update[key]
    return merged


def _preview_progressed(summary: dict[str, object]) -> bool:
    return any(
        _int_payload_value(summary, key) > 0
        for key in ("resolved_count", "matched_count", "no_preview_count", "not_found_count", "no_isrc_count")
    )


def _embedding_progressed(summary: dict[str, object]) -> bool:
    return _int_payload_value(summary, "embedded_count") > 0


def _int_payload_value(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    return value if isinstance(value, int) else 0


def _session_start_error_code(
    ready: bool,
    recommendation: DJBlock | None,
    *,
    has_recommendation_generator: bool,
) -> str | None:
    if not ready:
        return "insufficient_ready_tracks"
    if has_recommendation_generator and recommendation is None:
        return "no_recommendation_available"
    return None


def _initialize_embedding_schema(schema_db, embedding_config) -> None:
    initialize_schema(
        schema_db,
        dimensions=embedding_config.dimensions,
        model_name=embedding_config.model_name,
        model_version=embedding_config.model_version,
    )


def run_daemon() -> int:
    """Run the Claude DJ daemon until it is asked to quit."""
    app_dir = ensure_app_dir()
    runtime_file = get_runtime_file(app_dir)
    database_file = get_database_file(app_dir)
    embedding_config = get_embedding_config()
    db = connect(database_file)
    _initialize_embedding_schema(db, embedding_config)
    catalog_status = get_catalog_status(db)
    db.close()

    def initialize_embedding_schema(schema_db):
        _initialize_embedding_schema(schema_db, embedding_config)

    def spotify_indexer() -> IndexSummary:
        index_db = connect(database_file)
        try:
            initialize_embedding_schema(index_db)
            return index_spotify_playlists(
                index_db,
                token_file=get_spotify_token_file(app_dir),
            )
        finally:
            index_db.close()

    def preview_resolver() -> PreviewResolutionSummary:
        preview_db = connect(database_file)
        try:
            initialize_embedding_schema(preview_db)
            return resolve_deezer_previews(preview_db, limit=SYNC_CHUNK_SIZE)
        finally:
            preview_db.close()

    def embedding_generator() -> EmbeddingGenerationSummary:
        embedding_db = connect(database_file)
        try:
            initialize_embedding_schema(embedding_db)
            return generate_audio_embeddings(embedding_db, limit=SYNC_CHUNK_SIZE)
        finally:
            embedding_db.close()

    def recommendation_generator(recently_played_track_ids: set[int]) -> DJBlock | None:
        recommendation_db = connect(database_file)
        try:
            initialize_embedding_schema(recommendation_db)
            return generate_next_dj_block(
                recommendation_db,
                recently_played_track_ids=recently_played_track_ids,
            )
        finally:
            recommendation_db.close()

    server = create_server(
        catalog_status=catalog_status,
        spotify_indexer=spotify_indexer,
        preview_resolver=preview_resolver,
        embedding_generator=embedding_generator,
        recommendation_generator=recommendation_generator,
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
