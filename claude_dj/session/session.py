from __future__ import annotations

import random
import threading
import time
from typing import Any

from claude_dj.adapters import spotify
from claude_dj.catalog import db
from claude_dj.playback.port import PlaybackPort
from claude_dj.recommend import engine as recommend
from claude_dj.session.plan import Plan, PlanEvent

MODE_IDLE = "idle"
MODE_ATTACHED = "attached"
# Seed affinity modes: tops (~4w / ~6m / ~1y) + recently played (~right now).
_SEED_MODES = ("short_term", "medium_term", "long_term", "recently_played")

class Session:
    """DJ session: plan + Focus/Taste mint + playback reconcile."""

    def __init__(self, playback: PlaybackPort) -> None:
        self.playback = playback
        self._lock = threading.Lock()
        self.plan = Plan()
        self.mode = MODE_IDLE
        self.focus: list[float] | None = None
        self.taste: list[float] | None = None
        self.cooldown: dict[int, float] = {}
        # Exclusive end indices of each minted block in plan.tracks.
        # Invariant while attached: always two blocks ahead when possible.
        self._block_ends: list[int] = []

    @property
    def virtual_queue(self) -> list[dict[str, Any]]:
        return self.plan.tracks

    @property
    def queue_index(self) -> int:
        return self.plan.index

    @queue_index.setter
    def queue_index(self, value: int) -> None:
        self.plan.index = value

    @property
    def expected_id(self) -> str | None:
        return self.plan.expected_id

    @expected_id.setter
    def expected_id(self, value: str | None) -> None:
        self.plan.expected_id = value

    def status(self, conn) -> dict[str, Any]:
        """Status snapshot for /status and the Claude Code statusline."""
        state = None
        try:
            state = self.playback.get_state()
        except Exception:
            state = None

        now_playing: dict[str, Any] | None = None
        if self.mode == MODE_ATTACHED:
            cur = self.plan.current()
            if cur is not None:
                now_playing = {
                    "name": str(cur.get("name") or ""),
                    "artists": str(cur.get("artists") or ""),
                    "progress_ms": state.progress_ms if state else None,
                    "duration_ms": (
                        state.duration_ms
                        if state and state.duration_ms is not None
                        else cur.get("duration_ms")
                    ),
                    "spotify_id": str(cur.get("spotify_id") or ""),
                }
            elif state is not None and state.track_id:
                now_playing = {
                    "name": "",
                    "artists": "",
                    "progress_ms": state.progress_ms,
                    "duration_ms": state.duration_ms,
                    "spotify_id": state.track_id,
                }

        return {
            "mode": self.mode,
            "indexed": db.count_indexed(conn),
            "catalog_total": db.count_tracks(conn),
            "now_playing": now_playing,
        }

    def play(self, conn) -> dict[str, Any]:
        """Start DJ: resolve session start, mint block, start playback. Idempotent while attached."""
        with self._lock:
            if self.mode == MODE_ATTACHED and self.plan.tracks:
                return {"ok": True, "resumed": True}

            seed_rows, seed_mode, seed_error = self._fetch_seed_rows()
            start = recommend.resolve_session_start(conn, top_rows=seed_rows)
            if start is None:
                self._reset()
                return self._fail(
                    conn,
                    "not_ready",
                    "catalog has no indexed tracks yet; wait for sync or run: dj sync",
                )

            self.focus = list(start.focus)
            self.taste = list(start.taste) if start.taste is not None else None
            self.cooldown = {}

            first = self._mint(conn, advance=False)
            if first is None or not first.tracks:
                self._reset()
                return self._fail(
                    conn,
                    "empty_block",
                    "recommend returned no tracks",
                )
            second = self._mint(conn, advance=True)
            tracks = list(first.tracks)
            self._block_ends = [len(tracks)]
            if second is not None and second.tracks:
                tracks.extend(second.tracks)
                self._block_ends.append(len(tracks))

            self.plan.replace(tracks)
            self.playback.start_block(tracks)
            self.mode = MODE_ATTACHED
            out: dict[str, Any] = {
                "ok": True,
                "size": len(tracks),
                "source": start.source,
                "seed_mode": seed_mode,
            }
            if seed_error:
                out["seed_error"] = seed_error
            elif start.source == "random" and seed_rows is not None:
                out["seed_note"] = "no indexed intersection with seed tracks"
            return out

    def tick(self, conn) -> dict[str, Any]:
        """Read player state, observe the plan, handle the resulting event."""
        with self._lock:
            if self.mode != MODE_ATTACHED:
                return {"ok": True, "event": "idle"}

            try:
                state = self.playback.get_state()
            except Exception as exc:
                return {"ok": False, "event": "error", "detail": str(exc)}

            event = self.plan.observe(state)
            return self._handle_event(conn, event)

    def _fetch_seed_rows(
        self,
    ) -> tuple[list[dict[str, Any]] | None, str, str | None]:
        """Return (rows or None, seed_mode, error detail or None)."""
        mode = random.choice(_SEED_MODES)
        try:
            if mode == "recently_played":
                rows = list(spotify.iter_recently_played(limit=50))
            else:
                rows = list(spotify.iter_top_tracks(mode, limit=50))
            return rows, mode, None
        except Exception as exc:
            return None, mode, str(exc)

    def _mint(self, conn, *, advance: bool) -> recommend.Block | None:
        """Mint one block; update focus/cooldown. Returns None if focus missing."""
        if self.focus is None:
            return None
        if advance:
            self.focus = recommend.advance_focus(self.focus, self.taste)
        now = time.time()
        block = recommend.recommend_block(
            conn,
            focus=self.focus,
            taste=self.taste,
            cooldown=self.cooldown,
            now=now,
        )
        if not block.tracks:
            return block
        self.focus = list(block.focus)
        recommend.apply_cooldown(
            self.cooldown,
            [int(t["track_id"]) for t in block.tracks],
            now,
        )
        return block

    def _block_index(self) -> int | None:
        """Which minted block the cursor is in, or None if unknown."""
        if not self._block_ends:
            return None
        idx = self.plan.index
        for i, end in enumerate(self._block_ends):
            if idx < end:
                return i
        return len(self._block_ends) - 1

    def _ensure_two_blocks(self, conn) -> dict[str, Any] | None:
        """If we've entered the last loaded block, mint one more to keep two ahead.

        Mint failure is soft: stay attached on the remaining plan; retry next tick.
        """
        bi = self._block_index()
        if bi is None or bi < len(self._block_ends) - 1:
            return None
        block = self._mint(conn, advance=True)
        if block is None or not block.tracks:
            return {
                "ok": True,
                "event": "mint_deferred",
                "detail": "could not mint next block; will retry",
                "indexed": db.count_indexed(conn),
            }
        self.plan.append(block.tracks)
        self._block_ends.append(len(self.plan.tracks))
        self.playback.start_block(self.plan.remaining())
        return {"ok": True, "event": "minted", "size": block.size}

    def _fail(self, conn, error: str, detail: str) -> dict[str, Any]:
        """Structured play failure with catalog context for CLI/agents."""
        body: dict[str, Any] = {
            "ok": False,
            "error": error,
            "detail": detail,
            "indexed": db.count_indexed(conn),
            "catalog_total": db.count_tracks(conn),
        }
        try:
            from claude_dj.catalog import sync as catalog_sync

            body["syncing"] = catalog_sync.is_syncing()
        except Exception:
            body["syncing"] = False
        if error == "not_ready":
            body["hint"] = "dj sync" if not body["syncing"] else "wait for catalog sync"
        return body

    def _handle_event(self, conn, event: PlanEvent) -> dict[str, Any]:
        """Advance cursor; when the next block starts, mint one more."""
        if event.kind == "paused" or event.kind == "device_gone":
            return {"ok": True, "event": event.kind}

        if event.kind == "same":
            refilled = self._ensure_two_blocks(conn)
            if refilled is not None:
                return refilled
            return {"ok": True, "event": "ok"}

        if event.kind == "advanced":
            assert event.track_id is not None
            self.plan.move_to(event.track_id)
            refilled = self._ensure_two_blocks(conn)
            if refilled is not None:
                return refilled
            return {"ok": True, "event": "advanced", "track_id": event.track_id}

        self._reset()
        return {
            "ok": True,
            "event": "foreign",
            "track_id": event.track_id,
            "quit": True,
        }

    def _reset(self) -> None:
        """Idle the session and wipe plan + recommend state."""
        self.mode = MODE_IDLE
        self.plan.clear()
        self.focus = None
        self.taste = None
        self.cooldown = {}
        self._block_ends = []


__all__ = [
    "Plan",
    "PlanEvent",
    "Session",
    "MODE_IDLE",
    "MODE_ATTACHED",
]
