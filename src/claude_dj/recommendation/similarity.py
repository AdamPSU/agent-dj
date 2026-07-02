"""Embedding similarity recommendations for Claude DJ.

This module will own nearest-neighbor search and seed-song similarity selection.
"""

from dataclasses import dataclass
import sqlite3


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
