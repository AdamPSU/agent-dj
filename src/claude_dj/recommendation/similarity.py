"""Embedding similarity recommendations for Claude DJ.

This module will own nearest-neighbor search and seed-song similarity selection.
"""

from dataclasses import dataclass
import random
import sqlite3

from claude_dj.storage.db import (
    fetch_embedded_track_ids,
    fetch_embedded_tracks_for_source,
    fetch_playlist_sources_with_embedded_tracks,
)


MIN_DJ_BLOCK_SIZE = 3
MAX_DJ_BLOCK_SIZE = 8


_NEAREST_NEIGHBORS_QUERY = """
    SELECT track_id, distance
    FROM track_embeddings
    WHERE embedding MATCH ?
      AND k = ?
    ORDER BY distance
"""


@dataclass(frozen=True)
class SimilarTrack:
    """Nearest-neighbor result for one embedded track."""

    track_id: int
    distance: float


@dataclass(frozen=True)
class DJTrack:
    """Playable track selected for a DJ block."""

    track_id: int
    role: str
    distance: float | None


@dataclass(frozen=True)
class DJBlock:
    """One playlist-gated recommendation block."""

    source_id: int
    seed_track_id: int
    tracks: tuple[DJTrack, ...]

    def to_json(self) -> dict[str, object]:
        """Serialize the block for daemon responses."""
        return {
            "source_id": self.source_id,
            "seed_track_id": self.seed_track_id,
            "tracks": [
                {
                    "track_id": track.track_id,
                    "role": track.role,
                    "distance": track.distance,
                }
                for track in self.tracks
            ],
        }


def generate_next_dj_block(
    db: sqlite3.Connection,
    *,
    recently_played_track_ids: set[int] | None = None,
    min_block_size: int = MIN_DJ_BLOCK_SIZE,
    max_block_size: int = MAX_DJ_BLOCK_SIZE,
    rng: random.Random | None = None,
) -> DJBlock | None:
    """Generate the next playlist-gated DJ block from embedded tracks."""
    if min_block_size <= 0 or max_block_size < min_block_size:
        raise ValueError("DJ block size bounds are invalid.")

    chooser = rng or random.Random()
    excluded = _active_cooldown_exclusions(db, recently_played_track_ids or set())
    sources = fetch_playlist_sources_with_embedded_tracks(db, excluded_track_ids=excluded)
    if not sources and excluded:
        excluded = set()
        sources = fetch_playlist_sources_with_embedded_tracks(db, excluded_track_ids=excluded)
    if not sources:
        return None

    source = chooser.choice(sources)
    seed_candidates = fetch_embedded_tracks_for_source(
        db,
        source_id=source.source_id,
        excluded_track_ids=excluded,
    )
    if not seed_candidates and excluded:
        excluded = set()
        seed_candidates = fetch_embedded_tracks_for_source(db, source_id=source.source_id)
    if not seed_candidates:
        return None

    source_track_ids = {candidate.track_id for candidate in seed_candidates}
    seed_track_id = chooser.choice(seed_candidates).track_id
    target_size = chooser.randint(min_block_size, max_block_size)
    similar_tracks = _find_block_similar_tracks(
        db,
        seed_track_id=seed_track_id,
        limit=target_size - 1,
        excluded_track_ids=excluded,
        allowed_track_ids=source_track_ids,
    )
    tracks = [DJTrack(track_id=seed_track_id, role="seed", distance=None)]
    tracks.extend(
        DJTrack(track_id=track.track_id, role="similar", distance=track.distance)
        for track in similar_tracks
    )
    return DJBlock(source_id=source.source_id, seed_track_id=seed_track_id, tracks=tuple(tracks))


def find_similar_tracks(
    db: sqlite3.Connection,
    *,
    seed_track_id: int,
    limit: int = 10,
) -> list[SimilarTrack]:
    """Return nearest embedded tracks to the seed embedding, excluding the seed."""
    if limit <= 0:
        return []

    seed_embedding = _fetch_seed_embedding(db, seed_track_id)
    if seed_embedding is None:
        return []

    # Fetch one extra neighbor because sqlite-vec's KNN result includes the seed.
    rows = db.execute(_NEAREST_NEIGHBORS_QUERY, (seed_embedding, limit + 1)).fetchall()
    return _similar_tracks_excluding_seed(rows, seed_track_id=seed_track_id, limit=limit)


def _active_cooldown_exclusions(
    db: sqlite3.Connection,
    recently_played_track_ids: set[int],
) -> set[int]:
    embedded_track_ids = fetch_embedded_track_ids(db)
    if not embedded_track_ids:
        return set()
    if embedded_track_ids.issubset(recently_played_track_ids):
        return set()
    return recently_played_track_ids & embedded_track_ids


def _find_block_similar_tracks(
    db: sqlite3.Connection,
    *,
    seed_track_id: int,
    limit: int,
    excluded_track_ids: set[int],
    allowed_track_ids: set[int],
) -> list[SimilarTrack]:
    if limit <= 0:
        return []

    embedded_count = len(fetch_embedded_track_ids(db))
    if embedded_count == 0:
        return []

    candidates = find_similar_tracks(db, seed_track_id=seed_track_id, limit=embedded_count)
    selected: list[SimilarTrack] = []
    for candidate in candidates:
        if candidate.track_id not in allowed_track_ids:
            continue
        if candidate.track_id in excluded_track_ids:
            continue
        selected.append(candidate)
        if len(selected) == limit:
            break
    return selected


def _fetch_seed_embedding(db: sqlite3.Connection, seed_track_id: int) -> bytes | None:
    row = db.execute(
        "SELECT embedding FROM track_embeddings WHERE track_id = ?",
        (seed_track_id,),
    ).fetchone()
    return None if row is None else row["embedding"]


def _similar_tracks_excluding_seed(
    rows: list[sqlite3.Row],
    *,
    seed_track_id: int,
    limit: int,
) -> list[SimilarTrack]:
    similar_tracks: list[SimilarTrack] = []
    for row in rows:
        track_id = int(row["track_id"])
        if track_id == seed_track_id:
            continue

        similar_tracks.append(
            SimilarTrack(track_id=track_id, distance=float(row["distance"]))
        )
        if len(similar_tracks) == limit:
            break
    return similar_tracks
