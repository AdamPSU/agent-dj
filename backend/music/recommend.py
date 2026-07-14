import math
import random
import time
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from backend.storage import db

MIN_INDEXED = 50
VALID_N = frozenset({3, 4, 5})
DEFAULT_N = 5
DEFAULT_TAU = 0.15
COOLDOWN_SECONDS = 3 * 3600
LAST_WEIGHT = 0.7
RECENCY_WEIGHT = 0.3
TOP_TIME_RANGES = ("short_term", "medium_term", "long_term")
TOP_LIMIT = 50


def next_block_seed(
    last_embed: Sequence[float],
    recency_embed: Sequence[float] | None = None,
) -> list[float]:
    """Blend last track and optional recency (0.7/0.3), then L2-normalize.

    If recency is missing, return last as-is. No session_start term.
    """
    if recency_embed is None:
        return list(last_embed)
    if len(last_embed) != len(recency_embed):
        raise ValueError("embedding length mismatch")
    blended = [
        LAST_WEIGHT * a + RECENCY_WEIGHT * b
        for a, b in zip(last_embed, recency_embed, strict=True)
    ]
    norm = math.sqrt(sum(x * x for x in blended))
    if norm < 1e-12:
        return list(last_embed)
    return [x / norm for x in blended]


def sample_seed_from_top(
    conn,
    top_rows: Sequence[Mapping[str, Any]],
    *,
    tau: float = DEFAULT_TAU,
    rng: random.Random | None = None,
) -> list[float] | None:
    """Rank-softmax sample an embedding from ordered top tracks that are indexed.

    `top_rows` is API order (rank 0 first). Returns None if no indexed intersection.
    """
    if rng is None:
        rng = random.Random()
    eligible: list[dict[str, Any]] = []
    for row in top_rows:
        spotify_id = row.get("spotify_id")
        if not spotify_id:
            continue
        track = db.get_track_by_spotify_id(conn, str(spotify_id))
        if track is None:
            continue
        if str(track.get("status") or "") != "indexed":
            continue
        track_id = int(track["id"])
        emb = db.get_embedding(conn, track_id)
        if emb is None:
            continue
        eligible.append(
            {
                "track_id": track_id,
                "spotify_id": str(spotify_id),
                "embedding": emb,
            }
        )
    if not eligible:
        return None
    k = len(eligible)
    denom = max(k - 1, 1)
    candidates = [
        {
            "track_id": item["track_id"],
            "spotify_id": item["spotify_id"],
            "distance": float(r) / denom,
            "embedding": item["embedding"],
        }
        for r, item in enumerate(eligible)
    ]
    pick = softmax_sample(candidates, tau=tau, rng=rng)
    return list(pick["embedding"])


def apply_cooldown(
    cooldown: dict[int, float],
    track_ids: Iterable[int],
    now: float,
) -> dict[int, float]:
    """Mark tracks as played at `now`. Mutates and returns `cooldown`."""
    for track_id in track_ids:
        cooldown[int(track_id)] = now
    return cooldown


def softmax_sample(
    candidates: Sequence[Mapping[str, Any]],
    *,
    tau: float,
    rng: random.Random,
) -> Mapping[str, Any]:
    """Sample one candidate with P ∝ exp(−distance / τ)."""
    if not candidates:
        raise ValueError("no candidates")
    if len(candidates) == 1:
        return candidates[0]
    scores = [-float(c["distance"]) / tau for c in candidates]
    peak = max(scores)
    weights = [math.exp(s - peak) for s in scores]
    total = sum(weights)
    pick = rng.random() * total
    running = 0.0
    for candidate, weight in zip(candidates, weights, strict=True):
        running += weight
        if pick <= running:
            return candidate
    return candidates[-1]


def recommend_block(
    conn,
    *,
    n: int = DEFAULT_N,
    session_start_embed: list[float] | None = None,
    seed_embed: list[float] | None = None,
    cooldown: Mapping[int, float] | None = None,
    now: float | None = None,
    tau: float = DEFAULT_TAU,
    neighbor_k: int | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """
    Build one DJ block of n tracks via embedding nearest-neighbor + softmax.

    Does not mutate cooldown; caller should apply_cooldown when a block is used.
    """
    if now is None:
        now = time.time()
    if rng is None:
        rng = random.Random()
    cool = dict(cooldown or {})

    if n not in VALID_N:
        return {
            "ok": False,
            "error": "invalid_n",
            "detail": f"n must be one of {sorted(VALID_N)}, got {n}",
            "indexed": None,
        }

    indexed = db.count_indexed(conn)
    if indexed < MIN_INDEXED:
        return {
            "ok": False,
            "error": "not_ready",
            "detail": f"need at least {MIN_INDEXED} indexed tracks, have {indexed}",
            "indexed": indexed,
        }

    k = neighbor_k if neighbor_k is not None else max(30, 6 * n)

    if seed_embed is not None:
        working = list(seed_embed)
    else:
        track_ids = db.list_indexed_track_ids(conn)
        if not track_ids:
            return {
                "ok": False,
                "error": "not_ready",
                "detail": "no indexed tracks with embeddings",
                "indexed": indexed,
            }
        seed_id = rng.choice(track_ids)
        emb = db.get_embedding(conn, seed_id)
        if emb is None:
            return {
                "ok": False,
                "error": "not_ready",
                "detail": f"missing embedding for track {seed_id}",
                "indexed": indexed,
            }
        working = emb

    if session_start_embed is None:
        session_start = list(working)
    else:
        session_start = list(session_start_embed)

    chosen: set[int] = set()
    tracks: list[dict[str, Any]] = []

    for _ in range(n):
        neighbors = db.similar_tracks(conn, working, limit=k)
        eligible: list[dict[str, Any]] = []
        for row in neighbors:
            track_id = int(row["id"])
            if track_id in chosen:
                continue
            played_at = cool.get(track_id)
            if played_at is not None and (now - float(played_at)) < COOLDOWN_SECONDS:
                continue
            if str(row.get("status") or "") != "indexed":
                continue
            eligible.append(row)

        if not eligible:
            return {
                "ok": False,
                "error": "insufficient_eligible",
                "detail": f"no eligible neighbors for slot {len(tracks) + 1} of {n}",
                "indexed": indexed,
            }

        pick = softmax_sample(eligible, tau=tau, rng=rng)
        track_id = int(pick["id"])
        emb = db.get_embedding(conn, track_id)
        if emb is None:
            return {
                "ok": False,
                "error": "insufficient_eligible",
                "detail": f"missing embedding for selected track {track_id}",
                "indexed": indexed,
            }

        tracks.append(
            {
                "track_id": track_id,
                "spotify_id": pick["spotify_id"],
                "name": pick["name"],
                "artists": pick["artists"],
                "distance": float(pick["distance"]),
            }
        )
        chosen.add(track_id)
        working = emb

    return {
        "ok": True,
        "n": n,
        "tracks": tracks,
        "session_start_embed": session_start,
        "last_embed": working,
    }
