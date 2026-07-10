"""Long-running local process for Claude DJ.

This module owns session lifecycle, command handling, and the DJ loop.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import os
import threading
import time
import uuid

from claude_dj.config import (
    ensure_app_dir,
    ensure_narration_dir,
    get_database_file,
    get_embedding_config,
    get_narration_config,
    get_runtime_file,
    get_spotify_device_file,
    get_spotify_token_file,
    NarrationConfig,
)
from claude_dj.adapters.elevenlabs import synthesize_speech_to_file
from claude_dj.adapters.spotify import (
    SpotifyAuthError,
    SpotifyDevice,
    SpotifyNoActiveDeviceError,
    SpotifyPlaybackError,
    SpotifyPlaybackForbiddenError,
    SpotifyPlaybackState,
    add_to_queue_with_token,
    fetch_playback_state_with_token,
    pause_playback_with_token,
    resume_playback_with_token,
    set_repeat_mode_with_token,
    set_shuffle_with_token,
)
from claude_dj.devices import PlaybackDeviceResult, start_playback_with_device_policy
from claude_dj.audio.embeddings import EmbeddingGenerationSummary, generate_audio_embeddings
from claude_dj.audio.local_playback import play_audio_file
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
from claude_dj.narration.scripts import build_bridge_prompt, build_intro_prompt, generate_script_with_claude
from claude_dj.recommendation.similarity import DJBlock, generate_next_dj_block
from claude_dj.storage.db import (
    CatalogStatus,
    PlayableTrack,
    connect,
    fetch_tracks_by_ids,
    get_catalog_status,
    initialize_schema,
)


LOOPBACK_HOST = "127.0.0.1"
MIN_READY_TRACKS = 30
SYNC_CHUNK_SIZE = 10
TRACK_COOLDOWN = timedelta(hours=3)


SpotifyIndexer = Callable[[], IndexSummary]
PreviewResolver = Callable[[], PreviewResolutionSummary]
EmbeddingGenerator = Callable[[], EmbeddingGenerationSummary]
CatalogStepRunner = Callable[[], PreviewResolutionSummary | EmbeddingGenerationSummary]
RecommendationGenerator = Callable[[set[int]], DJBlock | None]
TrackHydrator = Callable[[tuple[int, ...]], list[PlayableTrack]]
PlaybackStarter = Callable[[tuple[str, ...]], PlaybackDeviceResult | None]
QueueAppender = Callable[[tuple[str, ...]], None]
PlaybackStateFetcher = Callable[[], SpotifyPlaybackState]
PlaybackOptionsSetter = Callable[[], None]
NarrationPreparer = Callable[[str, list[PlayableTrack], list[PlayableTrack] | None], Path | None]
NarrationPlayer = Callable[[Path], None]
PlaybackPauser = Callable[[], None]
PlaybackResumer = Callable[[], None]
ScriptGenerator = Callable[[str], str | None]
SpeechSynthesizer = Callable[[str, Path, NarrationConfig], Path]
PLAYBACK_POLL_SECONDS = 5.0
QUEUE_REPLENISH_THRESHOLD_TRACKS = 2
TRANSITION_SILENCE_SECONDS = 1.0
TRANSITION_AUDIO_WINDOW_SECONDS = 5.0


@dataclass
class PendingBridge:
    """Prepared narration for the handoff into the next Spotify block."""

    previous_tracks: list[PlayableTrack]
    next_tracks: list[PlayableTrack]
    next_uris: tuple[str, ...]
    audio_file: Path | None


@dataclass(frozen=True)
class BridgeTransitionPlan:
    """Timing plan for a prepared bridge narration."""

    delay_seconds: float
    pause_before_delay: bool
    play_narration: bool = True


@dataclass
class DaemonState:
    """In-memory daemon state for the local control server."""

    host: str
    port: int
    catalog_status: CatalogStatus
    spotify_indexer: SpotifyIndexer | None = None
    preview_resolver: PreviewResolver | None = None
    embedding_generator: EmbeddingGenerator | None = None
    recommendation_generator: RecommendationGenerator | None = None
    track_hydrator: TrackHydrator | None = None
    playback_starter: PlaybackStarter | None = None
    playback_state_fetcher: PlaybackStateFetcher | None = None
    playback_options_setter: PlaybackOptionsSetter | None = None
    queue_appender: QueueAppender | None = None
    narration_preparer: NarrationPreparer | None = None
    narration_player: NarrationPlayer | None = None
    playback_pauser: PlaybackPauser | None = None
    playback_resumer: PlaybackResumer | None = None
    pid: int = field(default_factory=os.getpid)
    active_session_id: str | None = None
    known_spotify_uris: list[str] = field(default_factory=list)
    current_block_tracks: list[PlayableTrack] = field(default_factory=list)
    pending_bridge: PendingBridge | None = None
    lookahead_thread: threading.Thread | None = None
    lookahead_generation: int = 0
    lookahead_error: str | None = None
    playback_monitor_status: str = "idle"
    playback_monitor_error: str | None = None
    playback_monitor_thread: threading.Thread | None = None
    playback_monitor_stop: threading.Event = field(default_factory=threading.Event)
    track_last_played_at: dict[int, datetime] = field(default_factory=dict)
    sync_status: str = "idle"
    sync_error: str | None = None
    sync_indexing: dict[str, dict[str, object]] = field(default_factory=lambda: _empty_indexing_payload())
    sync_thread: threading.Thread | None = None
    sync_condition: threading.Condition = field(default_factory=lambda: threading.Condition(threading.RLock()))


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
                "playback": self._playback_status_json(),
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
            _stop_playback_monitor(self.server.state)
            self._send_json(200, {"ok": True, "message": "Claude DJ daemon stopped."})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        """Silence default HTTP request logging for CLI use."""

    def _handle_session_start(self, body: dict[str, object]) -> None:
        session_id = str(body.get("session_id") or "local-cli")
        self.server.state.active_session_id = session_id
        attached_playback = _running_playback_payload(self.server.state)
        if attached_playback is not None:
            self._send_json(
                200,
                {
                    "ok": True,
                    "message": "Claude DJ session attached.",
                    "active_session_id": self.server.state.active_session_id,
                    "error_code": None,
                    "minimum_ready_tracks": MIN_READY_TRACKS,
                    "catalog": self.server.state.catalog_status.to_json(),
                    "indexing": self.server.state.sync_indexing,
                    "onboarding": {
                        "index_all_playlists": self.server.state.catalog_status.needs_spotify_index,
                        "resolve_previews": self.server.state.catalog_status.needs_preview_resolution,
                        "embed_tracks": self.server.state.catalog_status.needs_embeddings,
                    },
                    "sync": self._sync_status_json(),
                    "recommendation": None,
                    "playback": attached_playback,
                },
            )
            return
        self._start_sync_if_idle()
        self._wait_for_ready_tracks_or_sync_terminal()
        ready = self.server.state.catalog_status.ready_track_count >= MIN_READY_TRACKS
        has_recommendation_generator = self.server.state.recommendation_generator is not None
        recommendation = self._generate_recommendation() if ready and has_recommendation_generator else None
        playback = self._start_recommendation_playback(recommendation) if recommendation is not None else None
        if _playback_started(playback):
            _start_playback_monitor(self.server.state)
            _start_lookahead_preparation(self.server.state)
        self._send_json(
            200,
            {
                "ok": ready
                and (recommendation is not None or not has_recommendation_generator)
                and not _playback_failed(playback),
                "message": "Claude DJ session attached.",
                "active_session_id": self.server.state.active_session_id,
                "error_code": _session_start_error_code(
                    ready,
                    recommendation,
                    has_recommendation_generator=has_recommendation_generator,
                    playback=playback,
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
                "playback": playback,
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

    def _playback_status_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.server.state.playback_monitor_status,
            "known_track_count": len(self.server.state.known_spotify_uris),
        }
        if self.server.state.playback_monitor_error is not None:
            payload["error"] = self.server.state.playback_monitor_error
        return payload

    def _generate_recommendation(self) -> DJBlock | None:
        return _generate_recommendation_for_state(self.server.state)

    def _start_recommendation_playback(self, recommendation: DJBlock) -> dict[str, object] | None:
        track_hydrator = self.server.state.track_hydrator
        playback_starter = self.server.state.playback_starter
        if track_hydrator is None or playback_starter is None:
            return None

        track_ids = tuple(track.track_id for track in recommendation.tracks)
        playable_tracks = track_hydrator(track_ids)
        if not playable_tracks:
            return _playback_error_payload(
                "no_playable_tracks",
                "Claude DJ could not find playable Spotify tracks for the recommendation.",
            )

        spotify_uris = tuple(track.spotify_uri for track in playable_tracks)
        playback_uris = spotify_uris
        queued_uris: tuple[str, ...] = ()
        queue_appender = self.server.state.queue_appender
        if queue_appender is not None and len(spotify_uris) > 1:
            playback_uris = spotify_uris[:1]
            queued_uris = spotify_uris[1:]
        try:
            device_result = playback_starter(playback_uris)
            if self.server.state.playback_options_setter is not None:
                self.server.state.playback_options_setter()
            if queued_uris:
                queue_appender(queued_uris)
        except SpotifyAuthError as exc:
            return _playback_error_payload("spotify_auth_required", str(exc))
        except SpotifyNoActiveDeviceError as exc:
            return _playback_error_payload("spotify_no_active_device", str(exc))
        except SpotifyPlaybackForbiddenError as exc:
            return _playback_error_payload("spotify_playback_forbidden", str(exc))
        except (SpotifyPlaybackError, ValueError) as exc:
            return _playback_error_payload("spotify_playback_failed", str(exc))

        with self.server.state.sync_condition:
            self.server.state.known_spotify_uris = list(spotify_uris)
            self.server.state.current_block_tracks = list(playable_tracks)
        return _playback_success_payload(playable_tracks, device_result)

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
    track_hydrator: TrackHydrator | None = None,
    playback_starter: PlaybackStarter | None = None,
    playback_state_fetcher: PlaybackStateFetcher | None = None,
    playback_options_setter: PlaybackOptionsSetter | None = None,
    queue_appender: QueueAppender | None = None,
    narration_preparer: NarrationPreparer | None = None,
    narration_player: NarrationPlayer | None = None,
    playback_pauser: PlaybackPauser | None = None,
    playback_resumer: PlaybackResumer | None = None,
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
        track_hydrator=track_hydrator,
        playback_starter=playback_starter,
        playback_state_fetcher=playback_state_fetcher,
        playback_options_setter=playback_options_setter,
        queue_appender=queue_appender,
        narration_preparer=narration_preparer,
        narration_player=narration_player,
        playback_pauser=playback_pauser,
        playback_resumer=playback_resumer,
    )
    return server


def _play_intro_narration(state: DaemonState, tracks: list[PlayableTrack]) -> None:
    if state.narration_preparer is None or state.narration_player is None:
        return
    _best_effort_pause(state)
    try:
        audio_file = state.narration_preparer("intro", tracks, None)
        if audio_file is not None:
            state.narration_player(audio_file)
    except Exception:
        return


def _best_effort_pause(state: DaemonState) -> None:
    if state.playback_pauser is None:
        return
    try:
        state.playback_pauser()
    except Exception:
        return


def _start_playback_monitor(state: DaemonState, poll_seconds: float = PLAYBACK_POLL_SECONDS) -> None:
    if state.playback_state_fetcher is None:
        return
    existing_thread = state.playback_monitor_thread
    if existing_thread is not None and existing_thread.is_alive():
        return

    state.playback_monitor_stop.clear()
    state.playback_monitor_error = None
    state.playback_monitor_status = "running"
    thread = threading.Thread(
        target=_run_playback_monitor,
        args=(state, poll_seconds),
        daemon=True,
    )
    state.playback_monitor_thread = thread
    thread.start()


def _stop_playback_monitor(state: DaemonState) -> None:
    state.playback_monitor_stop.set()
    thread = state.playback_monitor_thread
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=2)
    state.playback_monitor_status = "idle"


def _run_playback_monitor(state: DaemonState, poll_seconds: float) -> None:
    while not state.playback_monitor_stop.is_set():
        try:
            fetcher = state.playback_state_fetcher
            if fetcher is not None:
                playback_state = fetcher()
                if not _transition_bridge_if_needed(state, playback_state):
                    _queue_replenishment_if_needed(state, playback_state)
        except Exception as exc:
            state.playback_monitor_error = str(exc)
            state.playback_monitor_status = "failed"
            return
        state.playback_monitor_stop.wait(timeout=poll_seconds)


def _queue_replenishment_if_needed(
    state: DaemonState,
    playback_state: SpotifyPlaybackState,
) -> dict[str, object] | None:
    if not playback_state.is_playing or playback_state.item_uri is None:
        return None
    if state.recommendation_generator is None or state.track_hydrator is None or state.queue_appender is None:
        return None

    with state.sync_condition:
        if state.pending_bridge is not None:
            return None
        try:
            current_index = state.known_spotify_uris.index(playback_state.item_uri)
        except ValueError:
            return None
        remaining_after_current = len(state.known_spotify_uris) - current_index - 1
        if remaining_after_current > QUEUE_REPLENISH_THRESHOLD_TRACKS:
            return None
        lookahead_thread = state.lookahead_thread
        if lookahead_thread is not None and lookahead_thread.is_alive():
            return None

    return _prepare_and_queue_next_block(state)


def _start_lookahead_preparation(state: DaemonState) -> None:
    if state.recommendation_generator is None or state.track_hydrator is None or state.queue_appender is None:
        return
    with state.sync_condition:
        if state.pending_bridge is not None:
            return
        existing_thread = state.lookahead_thread
        if existing_thread is not None and existing_thread.is_alive():
            return
        state.lookahead_generation += 1
        generation = state.lookahead_generation
        state.lookahead_error = None
        thread = threading.Thread(
            target=_run_lookahead_preparation,
            args=(state, generation),
            daemon=True,
        )
        state.lookahead_thread = thread
    thread.start()


def _run_lookahead_preparation(state: DaemonState, generation: int) -> None:
    try:
        _prepare_and_queue_next_block(state, generation=generation)
    except Exception as exc:
        with state.sync_condition:
            if state.lookahead_generation == generation:
                state.lookahead_error = str(exc)


def _prepare_and_queue_next_block(
    state: DaemonState,
    *,
    generation: int | None = None,
) -> dict[str, object] | None:
    if state.recommendation_generator is None or state.track_hydrator is None or state.queue_appender is None:
        return None

    with state.sync_condition:
        if state.pending_bridge is not None:
            return None
        if generation is not None and state.lookahead_generation != generation:
            return None
        previous_tracks = list(state.current_block_tracks)

    recommendation = _generate_recommendation_for_state(state)
    if recommendation is None:
        return None

    track_ids = tuple(track.track_id for track in recommendation.tracks)
    playable_tracks = state.track_hydrator(track_ids)
    if not playable_tracks:
        return None

    spotify_uris = tuple(track.spotify_uri for track in playable_tracks)
    bridge_audio = _prepare_bridge_narration(state, previous_tracks, playable_tracks)
    with state.sync_condition:
        if state.pending_bridge is not None or (generation is not None and state.lookahead_generation != generation):
            _remove_prepared_bridge_audio(bridge_audio)
            return None

    state.queue_appender(spotify_uris)
    with state.sync_condition:
        if state.pending_bridge is not None or (generation is not None and state.lookahead_generation != generation):
            _remove_prepared_bridge_audio(bridge_audio)
            return None
        state.known_spotify_uris.extend(spotify_uris)
        state.pending_bridge = PendingBridge(
            previous_tracks=previous_tracks,
            next_tracks=list(playable_tracks),
            next_uris=spotify_uris,
            audio_file=bridge_audio,
        )
    return {"queued_track_count": len(spotify_uris), "recommendation": recommendation.to_json()}


def _prepare_bridge_narration(
    state: DaemonState,
    previous_tracks: list[PlayableTrack],
    next_tracks: list[PlayableTrack],
) -> Path | None:
    if state.narration_preparer is None:
        return None
    try:
        return state.narration_preparer("bridge", previous_tracks, next_tracks)
    except Exception:
        return None


def _remove_prepared_bridge_audio(audio_file: Path | None) -> None:
    if audio_file is None:
        return
    try:
        audio_file.unlink(missing_ok=True)
    except OSError:
        pass


def _transition_bridge_if_needed(
    state: DaemonState,
    playback_state: SpotifyPlaybackState,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    pending = state.pending_bridge
    if pending is None:
        return False

    if pending.audio_file is None or state.narration_player is None:
        if playback_state.item_uri in pending.next_uris:
            _complete_pending_bridge(state, pending)
            return True
        return False

    transition_plan = _bridge_transition_plan(state, pending, playback_state)
    if transition_plan is None:
        return False

    if not transition_plan.play_narration:
        _complete_pending_bridge(state, pending)
        return True

    if transition_plan.pause_before_delay:
        _best_effort_pause(state)
        if transition_plan.delay_seconds > 0:
            sleep(transition_plan.delay_seconds)
    else:
        if transition_plan.delay_seconds > 0:
            sleep(transition_plan.delay_seconds)
        _best_effort_pause(state)
        sleep(TRANSITION_SILENCE_SECONDS)

    played_narration = False
    try:
        state.narration_player(pending.audio_file)
    except Exception:
        pass
    else:
        played_narration = True
    if played_narration:
        sleep(TRANSITION_SILENCE_SECONDS)
    _best_effort_resume(state)

    _complete_pending_bridge(state, pending)
    return True


def _bridge_transition_plan(
    state: DaemonState,
    pending: PendingBridge,
    playback_state: SpotifyPlaybackState,
) -> BridgeTransitionPlan | None:
    if not playback_state.is_playing or playback_state.item_uri is None:
        return None

    first_next_uri = pending.next_uris[0]
    if playback_state.item_uri == first_next_uri:
        progress_seconds = _milliseconds_to_seconds(playback_state.progress_ms)
        if progress_seconds is not None and progress_seconds > TRANSITION_AUDIO_WINDOW_SECONDS:
            return BridgeTransitionPlan(delay_seconds=0.0, pause_before_delay=True, play_narration=False)
        delay_seconds = TRANSITION_SILENCE_SECONDS
        if progress_seconds is not None:
            delay_seconds = max(0.0, TRANSITION_SILENCE_SECONDS - progress_seconds)
        return BridgeTransitionPlan(delay_seconds=delay_seconds, pause_before_delay=True)
    if playback_state.item_uri in pending.next_uris:
        return BridgeTransitionPlan(delay_seconds=0.0, pause_before_delay=True, play_narration=False)

    previous_uri = _pending_bridge_previous_uri(state, pending)
    if playback_state.item_uri != previous_uri:
        return None
    remaining_seconds = _remaining_track_seconds(playback_state)
    if remaining_seconds is None:
        return None
    if remaining_seconds + TRANSITION_SILENCE_SECONDS > TRANSITION_AUDIO_WINDOW_SECONDS:
        return None
    return BridgeTransitionPlan(delay_seconds=remaining_seconds, pause_before_delay=False)


def _pending_bridge_previous_uri(state: DaemonState, pending: PendingBridge) -> str | None:
    with state.sync_condition:
        next_start_index = len(state.known_spotify_uris) - len(pending.next_uris)
        if next_start_index <= 0:
            return None
        if tuple(state.known_spotify_uris[next_start_index:]) != pending.next_uris:
            return None
        return state.known_spotify_uris[next_start_index - 1]


def _remaining_track_seconds(playback_state: SpotifyPlaybackState) -> float | None:
    if playback_state.progress_ms is None or playback_state.duration_ms is None:
        return None
    return max(0.0, (playback_state.duration_ms - playback_state.progress_ms) / 1000)


def _milliseconds_to_seconds(value: int | None) -> float | None:
    return None if value is None else value / 1000


def _complete_pending_bridge(state: DaemonState, pending: PendingBridge) -> None:
    if pending.audio_file is not None:
        try:
            pending.audio_file.unlink(missing_ok=True)
        except OSError:
            pass
    start_next_lookahead = False
    with state.sync_condition:
        state.current_block_tracks = list(pending.next_tracks)
        if state.pending_bridge == pending:
            state.pending_bridge = None
            start_next_lookahead = True
    if start_next_lookahead:
        _start_lookahead_preparation(state)


def _best_effort_resume(state: DaemonState) -> None:
    if state.playback_resumer is None:
        return
    try:
        state.playback_resumer()
    except Exception:
        return


def _prepare_narration_audio(
    kind: str,
    previous_tracks: list[PlayableTrack],
    next_tracks: list[PlayableTrack] | None,
    *,
    narration_dir: Path,
    narration_config: NarrationConfig,
    script_generator: ScriptGenerator = generate_script_with_claude,
    speech_synthesizer: SpeechSynthesizer = synthesize_speech_to_file,
) -> Path | None:
    prompt = build_intro_prompt(previous_tracks) if kind == "intro" else build_bridge_prompt(previous_tracks, next_tracks or [])
    script = script_generator(prompt)
    if script is None:
        return None

    output_file = narration_dir / f"{uuid.uuid4().hex}.mp3"
    try:
        return speech_synthesizer(script, output_file, narration_config)
    except Exception:
        return None


def _play_and_remove_narration(audio_file: Path, *, player: Callable[[Path], None]) -> None:
    try:
        player(audio_file)
    finally:
        audio_file.unlink(missing_ok=True)


def _generate_recommendation_for_state(state: DaemonState) -> DJBlock | None:
    generator = state.recommendation_generator
    if generator is None:
        return None

    now = datetime.now(UTC)
    with state.sync_condition:
        recently_played = {
            track_id
            for track_id, played_at in state.track_last_played_at.items()
            if now - played_at < TRACK_COOLDOWN
        }
        recommendation = generator(recently_played)
        if recommendation is not None:
            for track in recommendation.tracks:
                state.track_last_played_at[track.track_id] = now
        return recommendation


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


def _playback_success_payload(
    tracks: list[PlayableTrack],
    device_result: PlaybackDeviceResult | None = None,
) -> dict[str, object]:
    first_track = tracks[0]
    payload: dict[str, object] = {
        "started": True,
        "track_count": len(tracks),
        "first_track": _playable_track_json(first_track),
    }
    if device_result is not None and device_result.device is not None:
        payload["device"] = _spotify_device_json(device_result.device)
        payload["device_fallback"] = device_result.used_fallback
        payload["preferred_device_unavailable"] = device_result.preferred_unavailable
    return payload


def _spotify_device_json(device: SpotifyDevice) -> dict[str, object]:
    return {
        "id": device.id,
        "name": device.name,
        "type": device.type,
        "is_active": device.is_active,
        "is_restricted": device.is_restricted,
    }


def _playable_track_json(track: PlayableTrack) -> dict[str, object]:
    return {
        "track_id": track.track_id,
        "title": track.title,
        "artist_name": track.artist_name,
        "spotify_uri": track.spotify_uri,
    }


def _playback_error_payload(error_code: str, message: str) -> dict[str, object]:
    return {"started": False, "error_code": error_code, "message": message}


def _playback_failed(playback: dict[str, object] | None) -> bool:
    return isinstance(playback, dict) and playback.get("started") is False


def _playback_started(playback: dict[str, object] | None) -> bool:
    return isinstance(playback, dict) and playback.get("started") is True


def _running_playback_payload(state: DaemonState) -> dict[str, object] | None:
    with state.sync_condition:
        if state.playback_monitor_status != "running" or not state.known_spotify_uris:
            return None
    return {"attached": True, "message": "Claude DJ is already playing."}


def _session_start_error_code(
    ready: bool,
    recommendation: DJBlock | None,
    *,
    has_recommendation_generator: bool,
    playback: dict[str, object] | None,
) -> str | None:
    if _playback_failed(playback):
        error_code = playback.get("error_code") if playback is not None else None
        return error_code if isinstance(error_code, str) else "spotify_playback_failed"
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
    narration_config = get_narration_config()
    narration_dir = ensure_narration_dir(app_dir) if narration_config is not None else None
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

    def track_hydrator(track_ids: tuple[int, ...]) -> list[PlayableTrack]:
        playback_db = connect(database_file)
        try:
            initialize_embedding_schema(playback_db)
            return fetch_tracks_by_ids(playback_db, track_ids)
        finally:
            playback_db.close()

    def playback_starter(spotify_uris: tuple[str, ...]) -> PlaybackDeviceResult | None:
        return start_playback_with_device_policy(
            token_file=get_spotify_token_file(app_dir),
            device_file=get_spotify_device_file(app_dir),
            spotify_uris=spotify_uris,
        )

    def playback_state_fetcher() -> SpotifyPlaybackState:
        return fetch_playback_state_with_token(token_file=get_spotify_token_file(app_dir))

    def playback_options_setter() -> None:
        token_file = get_spotify_token_file(app_dir)
        set_repeat_mode_with_token(token_file=token_file, state="off")
        set_shuffle_with_token(token_file=token_file, enabled=False)

    def queue_appender(spotify_uris: tuple[str, ...]) -> None:
        token_file = get_spotify_token_file(app_dir)
        for spotify_uri in spotify_uris:
            add_to_queue_with_token(token_file=token_file, spotify_uri=spotify_uri)

    def narration_preparer(
        kind: str,
        previous_tracks: list[PlayableTrack],
        next_tracks: list[PlayableTrack] | None,
    ) -> Path | None:
        if narration_config is None or narration_dir is None:
            return None
        return _prepare_narration_audio(
            kind,
            previous_tracks,
            next_tracks,
            narration_dir=narration_dir,
            narration_config=narration_config,
        )

    def narration_player(audio_file: Path) -> None:
        _play_and_remove_narration(audio_file, player=lambda path: play_audio_file(path))

    def playback_pauser() -> None:
        pause_playback_with_token(token_file=get_spotify_token_file(app_dir))

    def playback_resumer() -> None:
        resume_playback_with_token(token_file=get_spotify_token_file(app_dir))

    server = create_server(
        catalog_status=catalog_status,
        spotify_indexer=spotify_indexer,
        preview_resolver=preview_resolver,
        embedding_generator=embedding_generator,
        recommendation_generator=recommendation_generator,
        track_hydrator=track_hydrator,
        playback_starter=playback_starter,
        playback_state_fetcher=playback_state_fetcher,
        playback_options_setter=playback_options_setter,
        queue_appender=queue_appender,
        narration_preparer=narration_preparer,
        narration_player=narration_player,
        playback_pauser=playback_pauser,
        playback_resumer=playback_resumer,
    )
    host, port = server.server_address
    write_runtime_file(runtime_file, pid=os.getpid(), host=host, port=port)

    try:
        server.serve_forever()
    finally:
        _stop_playback_monitor(server.state)
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
