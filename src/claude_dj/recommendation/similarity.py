"""Embedding similarity recommendations for Claude DJ.

This module will own nearest-neighbor search and seed-song similarity selection.
"""

from dataclasses import dataclass
import sqlite3


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

    seed = db.execute(
        "SELECT embedding FROM track_embeddings WHERE track_id = ?",
        (seed_track_id,),
    ).fetchone()
    if seed is None:
        return []

    rows = db.execute(
        """
        SELECT track_id, distance
        FROM track_embeddings
        WHERE embedding MATCH ?
          AND k = ?
        ORDER BY distance
        """,
        (seed["embedding"], limit + 1),
    ).fetchall()
    return [
        SimilarTrack(track_id=track_id, distance=float(row["distance"]))
        for row in rows
        if (track_id := int(row["track_id"])) != seed_track_id
    ][:limit]
