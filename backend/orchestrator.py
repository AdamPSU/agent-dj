from __future__ import annotations

import random
import threading
import time
from typing import Any

from backend.music import recommend
from backend.music.playback import FakePlayback, PlaybackPort, PlayerState
from backend.storage import db

MODE_IDLE = "idle"
MODE_ATTACHED = "attached"
MODE_YIELDED = "yielded"

SKIP_RATIO = 0.9
SKIP_REMAINING_MS = 30_000


class Orchestrator:
    """DJ session: virtual queue, recommend blocks, playback port, reconcile ticks."""

    def __init__(
        self,
        playback: PlaybackPort,
        *,
        rng: random.Random | None = None,
        now: float | None = None,
        n: int = recommend.DEFAULT_N,
        top_tracks_fetcher=None,
    ) -> None:
        self.playback = playback
        self.rng = rng if rng is not None else random.Random()
        self.now = now
        self.n = n
        self.top_tracks_fetcher = top_tracks_fetcher
        self.mode = MODE_IDLE
        self.playing = False
        self.current_block: dict[str, Any] | None = None
        self.session_start_embed: list[float] | None = None
        self.last_embed: list[float] | None = None
        self.cooldown: dict[int, float] = {}
        self.virtual_queue: list[dict[str, Any]] = []
        self.queue_index = 0
        self.expected_id: str | None = None
        self._prev_progress_ms: int | None = None
        self._lock = threading.Lock()

    def _clock(self) -> float:
        return time.time() if self.now is None else self.now

    def status_snapshot(self, conn) -> dict[str, Any]:
        indexed = db.count_indexed(conn)
        remaining = self.virtual_queue[self.queue_index :]
        state = None
        try:
            state = self.playback.get_state()
        except Exception:
            state = None
        now_playing = None
        if state and state.track_id:
            now_playing = {
                "spotify_id": state.track_id,
                "progress_ms": state.progress_ms,
                "duration_ms": state.duration_ms,
                "is_playing": state.is_playing,
            }
        return {
            "mode": self.mode,
            "playing": self.mode == MODE_ATTACHED and self.playing,
            "current_block": self.current_block,
            "indexed": indexed,
            "recommend_ready": indexed >= recommend.MIN_INDEXED,
            "now_playing": now_playing,
            "virtual_queue": [
                {
                    "spotify_id": t.get("spotify_id"),
                    "name": t.get("name"),
                    "artists": t.get("artists"),
                }
                for t in remaining
            ],
        }

    def play(self, conn) -> dict[str, Any]:
        """Start/re-attach DJ; idempotent while attached."""
        with self._lock:
            if self.mode == MODE_ATTACHED and self.current_block is not None:
                return {
                    "ok": True,
                    "playing": True,
                    "mode": self.mode,
                    "block": self.current_block,
                    "resumed": True,
                }

            seed_embed = None
            if self.mode == MODE_YIELDED and self.last_embed is not None:
                recency = self._sample_recency_seed(conn)
                seed_embed = recommend.next_block_seed(self.last_embed, recency)
            elif self.mode == MODE_IDLE:
                seed_embed = self._sample_cold_seed(conn)

            return self._mint_and_start(
                conn,
                seed_embed=seed_embed,
                session_start_embed=None,
                replace_queue=True,
            )

    def _fetch_top_rows(self, time_range: str) -> list[dict[str, Any]]:
        fetcher = self.top_tracks_fetcher
        if fetcher is None:
            from backend.adapters import spotify

            fetcher = lambda tr: list(
                spotify.iter_top_tracks(tr, limit=recommend.TOP_LIMIT)
            )
        return list(fetcher(time_range))

    def _sample_cold_seed(self, conn) -> list[float] | None:
        """Uniform time_range + rank-softmax tops; None → recommend random seed."""
        try:
            time_range = self.rng.choice(list(recommend.TOP_TIME_RANGES))
            rows = self._fetch_top_rows(time_range)
            return recommend.sample_seed_from_top(conn, rows, rng=self.rng)
        except Exception:
            return None

    def _sample_recency_seed(self, conn) -> list[float] | None:
        """Always short_term tops for next-block recency leg."""
        try:
            rows = self._fetch_top_rows("short_term")
            return recommend.sample_seed_from_top(conn, rows, rng=self.rng)
        except Exception:
            return None

    def advance(self, conn) -> dict[str, Any]:
        """Play next planned track, or mint a new block if the queue is empty."""
        with self._lock:
            if self.mode != MODE_ATTACHED:
                return {
                    "ok": False,
                    "error": "not_playing",
                    "detail": "advance requires attached mode",
                }
            return self._play_next_or_mint(conn)

    def tick(self, conn) -> dict[str, Any]:
        """Poll playback and reconcile (monitor / tests)."""
        with self._lock:
            if self.mode != MODE_ATTACHED:
                return {"ok": True, "event": "idle", "mode": self.mode}

            try:
                state = self.playback.get_state()
            except Exception as exc:
                return {"ok": False, "event": "error", "detail": str(exc)}

            if state is None:
                return {"ok": True, "event": "device_gone", "mode": self.mode}

            if not state.is_playing:
                return {"ok": True, "event": "paused", "mode": self.mode}

            track_id = state.track_id
            if track_id is None:
                return {"ok": True, "event": "paused", "mode": self.mode}

            if track_id == self.expected_id:
                self._prev_progress_ms = state.progress_ms
                remaining = state.time_remaining_ms
                # Multi-URI block load: Spotify advances within the block.
                # Only mint early when the planned queue has no next track.
                if (
                    remaining is not None
                    and remaining < 5_000
                    and not self._has_next()
                ):
                    return self._finish_current_and_continue(conn, skipped=False)
                return {"ok": True, "event": "ok", "mode": self.mode}

            # Track changed (user skip or natural advance inside multi-URI block)
            planned_ids = {
                str(t["spotify_id"]) for t in self.virtual_queue[self.queue_index :]
            }
            if track_id in planned_ids:
                skipped = self._was_skip()
                self._reconcile_to(track_id)
                self._cooldown_current()
                event = "skipped" if skipped else "advanced"
                self._prev_progress_ms = state.progress_ms
                return {"ok": True, "event": event, "mode": self.mode, "track_id": track_id}

            # Foreign track
            self.mode = MODE_YIELDED
            self.playing = False
            self.expected_id = None
            return {"ok": True, "event": "yielded", "mode": self.mode, "track_id": track_id}

    def _was_skip(self) -> bool:
        prev = self._prev_progress_ms
        if prev is None:
            return False
        # Without duration on previous, treat mid-track jump as skip if progress was low.
        return prev < int(180_000 * SKIP_RATIO)  # fallback; refined when state has duration

    def _was_skip_from_state(self, prev_state: PlayerState | None) -> bool:
        if prev_state is None or prev_state.duration_ms is None or prev_state.progress_ms is None:
            return self._was_skip()
        ratio = prev_state.progress_ms / max(1, prev_state.duration_ms)
        remaining = prev_state.duration_ms - prev_state.progress_ms
        return ratio < SKIP_RATIO and remaining >= SKIP_REMAINING_MS

    def _has_next(self) -> bool:
        return self.queue_index + 1 < len(self.virtual_queue)

    def _reconcile_to(self, track_id: str) -> None:
        for i in range(self.queue_index, len(self.virtual_queue)):
            if str(self.virtual_queue[i]["spotify_id"]) == track_id:
                self.queue_index = i
                self.expected_id = track_id
                return
        self.expected_id = track_id

    def _cooldown_current(self) -> None:
        if not self.virtual_queue or self.queue_index >= len(self.virtual_queue):
            return
        track = self.virtual_queue[self.queue_index]
        tid = track.get("track_id")
        if tid is not None:
            recommend.apply_cooldown(self.cooldown, [int(tid)], self._clock())

    def _finish_current_and_continue(self, conn, *, skipped: bool) -> dict[str, Any]:
        result = self._play_next_or_mint(conn)
        result["event"] = "skipped" if skipped else "advanced"
        return result

    def _play_next_or_mint(self, conn) -> dict[str, Any]:
        if self._has_next():
            # Force-advance: re-load remaining plan as multi-URI so skip still works.
            self.queue_index += 1
            remaining = self.virtual_queue[self.queue_index :]
            track = remaining[0]
            sid = str(track["spotify_id"])
            self.playback.start_block(remaining)
            self.expected_id = sid
            self._cooldown_current()
            self.playing = True
            self.mode = MODE_ATTACHED
            return {
                "ok": True,
                "playing": True,
                "mode": self.mode,
                "block": self.current_block,
                "track": track,
            }

        # Need a new block
        if self.last_embed is None:
            return {
                "ok": False,
                "error": "not_playing",
                "detail": "session embeddings missing for next block",
            }
        recency = self._sample_recency_seed(conn)
        seed = recommend.next_block_seed(self.last_embed, recency)
        return self._mint_and_start(
            conn,
            seed_embed=seed,
            session_start_embed=self.session_start_embed,
            replace_queue=False,
        )

    def _mint_and_start(
        self,
        conn,
        *,
        seed_embed: list[float] | None,
        session_start_embed: list[float] | None,
        replace_queue: bool,
    ) -> dict[str, Any]:
        indexed = db.count_indexed(conn)
        if indexed < recommend.MIN_INDEXED:
            return {
                "ok": False,
                "error": "not_ready",
                "indexed": indexed,
                "detail": f"need at least {recommend.MIN_INDEXED} indexed tracks, have {indexed}",
            }

        block = recommend.recommend_block(
            conn,
            n=self.n,
            seed_embed=seed_embed,
            session_start_embed=session_start_embed,
            cooldown=self.cooldown,
            now=self._clock(),
            rng=self.rng,
        )
        if not block.get("ok"):
            return {
                "ok": False,
                "error": block.get("error", "recommend_failed"),
                "detail": block.get("detail"),
                "indexed": block.get("indexed", indexed),
            }

        tracks = list(block["tracks"])
        public_block = {"n": block["n"], "tracks": tracks}
        self.current_block = public_block
        self.session_start_embed = list(block["session_start_embed"])
        self.last_embed = list(block["last_embed"])

        if replace_queue or not self.virtual_queue:
            self.virtual_queue = list(tracks)
            self.queue_index = 0
        else:
            self.virtual_queue.extend(tracks)
            self.queue_index = len(self.virtual_queue) - len(tracks)

        # Always multi-URI load the new block so Connect skip works within it.
        self.playback.start_block(tracks)

        head = self.virtual_queue[self.queue_index]
        self.expected_id = str(head["spotify_id"])
        self._cooldown_current()
        self.mode = MODE_ATTACHED
        self.playing = True
        self._prev_progress_ms = 0

        return {
            "ok": True,
            "playing": True,
            "mode": self.mode,
            "block": public_block,
            "resumed": False,
        }


# Re-export for existing imports
__all__ = [
    "Orchestrator",
    "FakePlayback",
    "PlaybackPort",
    "MODE_IDLE",
    "MODE_ATTACHED",
    "MODE_YIELDED",
]
