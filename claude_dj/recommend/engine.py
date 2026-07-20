"""Focus + Taste block recommender (pure; no Spotify HTTP).

Callers must treat resolve_session_start() → None as not ready (no indexed
embeddings). recommend_block may still return an empty Block if the
neighborhood is exhausted.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from claude_dj.catalog import db

DEFAULT_SIZE = 5
DEFAULT_TAU = 0.15
NEIGHBOR_K = 40
W_TASTE = 0.35
FOCUS_NUDGE = 0.75
ADVANCE_DELTA = 0.30
ADVANCE_NOISE = 0.05
COOLDOWN_SECONDS = 3 * 3600
_NORM_EPS = 1e-12


@dataclass(frozen=True)
class Block:
    tracks: list[dict[str, Any]]
    focus: list[float]
    size: int
    playlist_id: int | None = None


@dataclass(frozen=True)
class SessionStart:
    focus: list[float]
    taste: list[float] | None
    source: Literal["tops", "random"]


def l2_normalize(v: Sequence[float]) -> list[float]:
    s = math.sqrt(sum(float(x) * float(x) for x in v))
    if s < _NORM_EPS:
        return [float(x) for x in v]
    return [float(x) / s for x in v]


def _norm(v: Sequence[float]) -> float:
    return math.sqrt(sum(float(x) * float(x) for x in v))


def _is_degenerate(v: Sequence[float]) -> bool:
    return _norm(v) < _NORM_EPS


def _euclid(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def softmax_sample(
    items: Sequence[Any],
    scores: Sequence[float],
    *,
    tau: float = DEFAULT_TAU,
    rng: random.Random | None = None,
) -> Any:
    if not items:
        raise ValueError("softmax_sample on empty items")
    if len(items) != len(scores):
        raise ValueError("items/scores length mismatch")
    rng = rng or random.Random()
    t = max(float(tau), _NORM_EPS)
    m = max(float(s) for s in scores)
    exps = [math.exp((float(s) - m) / t) for s in scores]
    total = sum(exps) or 1.0
    r = rng.random() * total
    acc = 0.0
    for item, e in zip(items, exps):
        acc += e
        if r <= acc:
            return item
    return items[-1]


def apply_cooldown(
    cooldown: dict[int, float],
    track_ids: Sequence[int],
    now: float,
    *,
    seconds: float = COOLDOWN_SECONDS,
) -> None:
    expiry = float(now) + float(seconds)
    for tid in track_ids:
        cooldown[int(tid)] = expiry


def _active_cooldown(cooldown: dict[int, float] | None, now: float) -> set[int]:
    if not cooldown:
        return set()
    return {int(tid) for tid, exp in cooldown.items() if float(exp) > now}


def _track_payload(
    row: dict[str, Any], *, playlist_id: int | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "track_id": int(row["id"]),
        "spotify_id": str(row["spotify_id"]),
        "name": row.get("name"),
        "artists": row.get("artists"),
        "duration_ms": row.get("duration_ms"),
    }
    if playlist_id is not None:
        out["playlist_id"] = int(playlist_id)
    return out


def _lock_playlist(
    conn,
    *,
    focus: Sequence[float],
    cooled: set[int],
    neighbor_k: int,
    previous_playlist_id: int | None,
) -> int | None:
    """Pick one playlist from the best global neighbor (soft-avoid previous)."""
    neighbors = db.similar_tracks(conn, list(focus), limit=neighbor_k)
    # Ordered candidates: first occurrence wins (probe distance order, then playlist id).
    ordered: list[int] = []
    seen: set[int] = set()
    for row in neighbors:
        tid = int(row["id"])
        if tid in cooled:
            continue
        if db.get_embedding(conn, tid) is None:
            continue
        for pl in db.list_playlists_for_track(conn, tid):
            pid = int(pl["id"])
            if pid in seen:
                continue
            ok = False
            for m in db.similar_tracks(
                conn, list(focus), limit=neighbor_k, playlist_id=pid
            ):
                mid = int(m["id"])
                if mid in cooled:
                    continue
                if db.get_embedding(conn, mid) is None:
                    continue
                ok = True
                break
            if not ok:
                continue
            seen.add(pid)
            ordered.append(pid)

    if not ordered:
        return None
    if previous_playlist_id is not None:
        for pid in ordered:
            if pid != int(previous_playlist_id):
                return pid
    return ordered[0]


def recommend_block(
    conn,
    *,
    focus: Sequence[float],
    taste: Sequence[float] | None = None,
    size: int = DEFAULT_SIZE,
    cooldown: dict[int, float] | None = None,
    now: float | None = None,
    rng: random.Random | None = None,
    neighbor_k: int = NEIGHBOR_K,
    tau: float = DEFAULT_TAU,
    w_taste: float = W_TASTE,
    focus_nudge: float = FOCUS_NUDGE,
    previous_playlist_id: int | None = None,
) -> Block:
    """Mint a block locked to one playlist. Empty neighborhood ends early."""
    rng = rng or random.Random()
    now_ts = time.time() if now is None else float(now)
    cooled = _active_cooldown(cooldown, now_ts)

    f = l2_normalize(focus)
    t_vec = (
        l2_normalize(taste)
        if taste is not None and not _is_degenerate(taste)
        else None
    )

    locked = _lock_playlist(
        conn,
        focus=f,
        cooled=cooled,
        neighbor_k=neighbor_k,
        previous_playlist_id=previous_playlist_id,
    )
    if locked is None:
        return Block(tracks=[], focus=f, size=0, playlist_id=None)

    tracks: list[dict[str, Any]] = []
    in_block: set[int] = set()
    alpha = float(focus_nudge)

    for _ in range(size):
        neighbors = db.similar_tracks(
            conn, f, limit=neighbor_k, playlist_id=locked
        )
        eligible: list[dict[str, Any]] = []
        embeds: list[list[float]] = []
        for row in neighbors:
            tid = int(row["id"])
            if tid in in_block or tid in cooled:
                continue
            emb = db.get_embedding(conn, tid)
            if emb is None:
                continue
            eligible.append(row)
            embeds.append(emb)

        if not eligible:
            break

        scores: list[float] = []
        for row, emb in zip(eligible, embeds):
            raw_d = row.get("distance")
            d_f = float(raw_d) if raw_d is not None else _euclid(f, emb)
            score = -d_f
            if t_vec is not None:
                score -= float(w_taste) * _euclid(t_vec, emb)
            scores.append(score)

        pick_i = int(softmax_sample(list(range(len(eligible))), scores, tau=tau, rng=rng))
        row = eligible[pick_i]
        emb = embeds[pick_i]
        tid = int(row["id"])
        tracks.append(_track_payload(row, playlist_id=locked))
        in_block.add(tid)
        f = l2_normalize([(1.0 - alpha) * a + alpha * b for a, b in zip(f, emb)])

    return Block(tracks=tracks, focus=f, size=len(tracks), playlist_id=locked)


def advance_focus(
    focus: Sequence[float],
    taste: Sequence[float] | None = None,
    *,
    rng: random.Random | None = None,
    delta: float = ADVANCE_DELTA,
    noise: float = ADVANCE_NOISE,
) -> list[float]:
    rng = rng or random.Random()
    f = l2_normalize(focus)
    dim = len(f)
    noise_vec = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    nn = _norm(noise_vec)
    if nn >= _NORM_EPS:
        noise_vec = [float(noise) * (x / nn) for x in noise_vec]
    else:
        noise_vec = [0.0] * dim

    if taste is None or _is_degenerate(taste):
        return l2_normalize([a + b for a, b in zip(f, noise_vec)])

    t = l2_normalize(taste)
    d = float(delta)
    blended = [(1.0 - d) * a + d * b + c for a, b, c in zip(f, t, noise_vec)]
    out = l2_normalize(blended)
    if _is_degenerate(out):
        return f
    return out


def sample_seed_from_tops(
    conn,
    top_rows: Sequence[dict[str, Any]],
    *,
    tau: float = DEFAULT_TAU,
    rng: random.Random | None = None,
) -> list[float] | None:
    """Rank-softmax among tops that are indexed locally; None if empty intersection."""
    rng = rng or random.Random()
    candidates: list[list[float]] = []
    for row in top_rows:
        sid = row.get("spotify_id")
        if not sid:
            continue
        track = db.get_track_by_spotify_id(conn, str(sid))
        if track is None:
            continue
        tid = int(track["id"])
        emb = db.get_embedding(conn, tid)
        if emb is None:
            continue
        if str(track.get("status")) != "indexed":
            continue
        candidates.append(emb)

    if not candidates:
        return None

    k = len(candidates)
    scores = [-(r / max(k - 1, 1)) for r in range(k)]
    pick_i = int(softmax_sample(list(range(k)), scores, tau=tau, rng=rng))
    return l2_normalize(candidates[pick_i])


def _random_indexed_embed(conn, rng: random.Random) -> list[float] | None:
    ids = db.list_indexed_track_ids(conn)
    if not ids:
        return None
    tid = int(rng.choice(ids))
    emb = db.get_embedding(conn, tid)
    if emb is None:
        return None
    return l2_normalize(emb)


def resolve_session_start(
    conn,
    *,
    top_rows: Sequence[dict[str, Any]] | None = None,
    rng: random.Random | None = None,
) -> SessionStart | None:
    """Build F₀ and optional T from top rows. None when the catalog has no embeddings."""
    rng = rng or random.Random()
    if top_rows:
        seed = sample_seed_from_tops(conn, top_rows, rng=rng)
        if seed is not None:
            return SessionStart(focus=list(seed), taste=list(seed), source="tops")

    focus = _random_indexed_embed(conn, rng)
    if focus is None:
        return None
    return SessionStart(focus=focus, taste=None, source="random")


__all__ = [
    "DEFAULT_SIZE",
    "DEFAULT_TAU",
    "NEIGHBOR_K",
    "W_TASTE",
    "FOCUS_NUDGE",
    "ADVANCE_DELTA",
    "ADVANCE_NOISE",
    "COOLDOWN_SECONDS",
    "Block",
    "SessionStart",
    "l2_normalize",
    "softmax_sample",
    "apply_cooldown",
    "recommend_block",
    "advance_focus",
    "sample_seed_from_tops",
    "resolve_session_start",
]
