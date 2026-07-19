import sqlite3
import struct
from pathlib import Path

import sqlite_vec

from claude_dj.embeddings import EMBED_DIM
from claude_dj.config import APP_DIR, DB_PATH

STATUSES = frozenset({"pending", "indexed", "skipped", "retry"})


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the local catalog database and enable vector search."""
    db_path = path or DB_PATH
    if db_path != Path(":memory:"):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create catalog tables if they do not already exist."""
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY,
            spotify_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            snapshot_id TEXT,
            owner_spotify_id TEXT,
            tracks_total INTEGER,
            synced_at TEXT
        );

        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY,
            spotify_id TEXT NOT NULL UNIQUE,
            isrc TEXT,
            name TEXT NOT NULL,
            artists TEXT NOT NULL,
            album_name TEXT,
            duration_ms INTEGER,
            deezer_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'indexed', 'skipped', 'retry')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_tracks_status ON tracks(status);
        CREATE INDEX IF NOT EXISTS idx_tracks_isrc ON tracks(isrc);

        CREATE TABLE IF NOT EXISTS playlist_tracks (
            playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
            track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
            position INTEGER,
            added_at TEXT,
            PRIMARY KEY (playlist_id, track_id)
        );

        CREATE INDEX IF NOT EXISTS idx_playlist_tracks_track ON playlist_tracks(track_id);

        CREATE VIRTUAL TABLE IF NOT EXISTS track_embeddings USING vec0(
            track_id INTEGER PRIMARY KEY,
            embedding float[{EMBED_DIM}]
        );
        """
    )
    conn.commit()


def serialize_f32(vector: list[float]) -> bytes:
    """Pack floats into the binary form sqlite-vec expects."""
    if len(vector) != EMBED_DIM:
        raise ValueError(f"expected {EMBED_DIM}-d vector, got {len(vector)}")
    return struct.pack(f"{EMBED_DIM}f", *vector)


def deserialize_f32(blob: bytes) -> list[float]:
    """Unpack a sqlite-vec float blob into a Python list."""
    expected = EMBED_DIM * 4
    if len(blob) != expected:
        raise ValueError(f"expected {expected}-byte blob, got {len(blob)}")
    return list(struct.unpack(f"{EMBED_DIM}f", blob))


def upsert_playlist(
    conn: sqlite3.Connection,
    *,
    spotify_id: str,
    name: str,
    snapshot_id: str | None = None,
    owner_spotify_id: str | None = None,
    tracks_total: int | None = None,
    synced_at: str | None = None,
) -> int:
    """Insert or update a playlist; returns its local id."""
    conn.execute(
        """
        INSERT INTO playlists (
            spotify_id, name, snapshot_id, owner_spotify_id, tracks_total, synced_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(spotify_id) DO UPDATE SET
            name = excluded.name,
            snapshot_id = COALESCE(excluded.snapshot_id, playlists.snapshot_id),
            owner_spotify_id = COALESCE(excluded.owner_spotify_id, playlists.owner_spotify_id),
            tracks_total = COALESCE(excluded.tracks_total, playlists.tracks_total),
            synced_at = COALESCE(excluded.synced_at, playlists.synced_at)
        """,
        (spotify_id, name, snapshot_id, owner_spotify_id, tracks_total, synced_at),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM playlists WHERE spotify_id = ?",
        (spotify_id,),
    ).fetchone()
    return int(row["id"])


def upsert_track(
    conn: sqlite3.Connection,
    *,
    spotify_id: str,
    name: str,
    artists: str,
    isrc: str | None = None,
    album_name: str | None = None,
    duration_ms: int | None = None,
    deezer_id: int | None = None,
    status: str = "pending",
) -> int:
    """Insert or update a track; returns its local id."""
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status}")
    conn.execute(
        """
        INSERT INTO tracks (
            spotify_id, isrc, name, artists, album_name, duration_ms, deezer_id, status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(spotify_id) DO UPDATE SET
            isrc = COALESCE(excluded.isrc, tracks.isrc),
            name = excluded.name,
            artists = excluded.artists,
            album_name = COALESCE(excluded.album_name, tracks.album_name),
            duration_ms = COALESCE(excluded.duration_ms, tracks.duration_ms),
            deezer_id = COALESCE(excluded.deezer_id, tracks.deezer_id),
            status = CASE
                WHEN tracks.status = 'indexed' THEN tracks.status
                ELSE excluded.status
            END,
            updated_at = datetime('now')
        """,
        (spotify_id, isrc, name, artists, album_name, duration_ms, deezer_id, status),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM tracks WHERE spotify_id = ?",
        (spotify_id,),
    ).fetchone()
    return int(row["id"])


def set_playlist_tracks(
    conn: sqlite3.Connection,
    playlist_id: int,
    members: list[tuple[int, int | None, str | None]],
) -> None:
    """Replace membership for one playlist: (track_id, position, added_at)."""
    conn.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
    conn.executemany(
        """
        INSERT INTO playlist_tracks (playlist_id, track_id, position, added_at)
        VALUES (?, ?, ?, ?)
        """,
        [(playlist_id, track_id, position, added_at) for track_id, position, added_at in members],
    )
    conn.commit()


def set_status(conn: sqlite3.Connection, track_id: int, status: str) -> None:
    """Update a track's pipeline status."""
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status}")
    conn.execute(
        """
        UPDATE tracks
        SET status = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (status, track_id),
    )
    conn.commit()


def upsert_embedding(conn: sqlite3.Connection, track_id: int, vector: list[float]) -> None:
    """Store or replace the music fingerprint for a track and mark it indexed."""
    blob = serialize_f32(vector)
    conn.execute("DELETE FROM track_embeddings WHERE track_id = ?", (track_id,))
    conn.execute(
        "INSERT INTO track_embeddings(track_id, embedding) VALUES (?, ?)",
        (track_id, blob),
    )
    conn.execute(
        """
        UPDATE tracks
        SET status = 'indexed', updated_at = datetime('now')
        WHERE id = ?
        """,
        (track_id,),
    )
    conn.commit()


def get_track(conn: sqlite3.Connection, track_id: int) -> dict | None:
    """Fetch one track by local id."""
    row = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    return dict(row) if row else None


def get_track_by_spotify_id(conn: sqlite3.Connection, spotify_id: str) -> dict | None:
    """Fetch one track by Spotify id."""
    row = conn.execute(
        "SELECT * FROM tracks WHERE spotify_id = ?",
        (spotify_id,),
    ).fetchone()
    return dict(row) if row else None


def get_embedding(conn: sqlite3.Connection, track_id: int) -> list[float] | None:
    """Return the stored embedding for a track, or None if missing."""
    row = conn.execute(
        "SELECT embedding FROM track_embeddings WHERE track_id = ?",
        (track_id,),
    ).fetchone()
    if row is None:
        return None
    blob = row["embedding"]
    if blob is None:
        return None
    return deserialize_f32(bytes(blob))


def list_indexed_track_ids(conn: sqlite3.Connection) -> list[int]:
    """Local ids of indexed tracks that have an embedding row."""
    rows = conn.execute(
        """
        SELECT t.id
        FROM tracks AS t
        INNER JOIN track_embeddings AS e ON e.track_id = t.id
        WHERE t.status = 'indexed'
        ORDER BY t.id
        """
    ).fetchall()
    return [int(row["id"]) for row in rows]


def count_indexed(conn: sqlite3.Connection) -> int:
    """How many tracks are indexed with an embedding."""
    return len(list_indexed_track_ids(conn))


def count_tracks(conn: sqlite3.Connection) -> int:
    """How many track rows exist in the catalog (all statuses)."""
    row = conn.execute("SELECT COUNT(*) AS n FROM tracks").fetchone()
    return int(row["n"])


def get_playlist_by_spotify_id(conn: sqlite3.Connection, spotify_id: str) -> dict | None:
    """Fetch one playlist by Spotify id."""
    row = conn.execute(
        "SELECT * FROM playlists WHERE spotify_id = ?",
        (spotify_id,),
    ).fetchone()
    return dict(row) if row else None


def list_tracks(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    """List tracks, optionally filtered by status."""
    if status is None:
        rows = conn.execute("SELECT * FROM tracks ORDER BY id").fetchall()
    else:
        if status not in STATUSES:
            raise ValueError(f"invalid status: {status}")
        rows = conn.execute(
            "SELECT * FROM tracks WHERE status = ? ORDER BY id",
            (status,),
        ).fetchall()
    return [dict(row) for row in rows]


def track_status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Count tracks in each pipeline status."""
    counts = {status: 0 for status in STATUSES}
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM tracks GROUP BY status"
    ).fetchall()
    for row in rows:
        counts[str(row["status"])] = int(row["n"])
    return counts


def playlist_count(conn: sqlite3.Connection) -> int:
    """How many playlists are stored locally."""
    row = conn.execute("SELECT COUNT(*) AS n FROM playlists").fetchone()
    return int(row["n"])


def delete_track(conn: sqlite3.Connection, track_id: int) -> None:
    """Remove a track, its membership rows, and its embedding."""
    conn.execute("DELETE FROM track_embeddings WHERE track_id = ?", (track_id,))
    conn.execute("DELETE FROM playlist_tracks WHERE track_id = ?", (track_id,))
    conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
    conn.commit()


def delete_orphan_tracks(conn: sqlite3.Connection) -> int:
    """Delete tracks that no longer appear in any playlist. Returns how many were removed."""
    rows = conn.execute(
        """
        SELECT t.id
        FROM tracks AS t
        LEFT JOIN playlist_tracks AS pt ON pt.track_id = t.id
        WHERE pt.track_id IS NULL
        """
    ).fetchall()
    for row in rows:
        delete_track(conn, int(row["id"]))
    return len(rows)


def similar_tracks(
    conn: sqlite3.Connection,
    vector: list[float],
    *,
    limit: int = 10,
    exclude_track_id: int | None = None,
) -> list[dict]:
    """Find tracks whose embeddings are closest to the given vector."""
    blob = serialize_f32(vector)
    fetch_k = limit + 1 if exclude_track_id is not None else limit
    rows = conn.execute(
        """
        SELECT
            t.*,
            e.distance
        FROM track_embeddings AS e
        JOIN tracks AS t ON t.id = e.track_id
        WHERE e.embedding MATCH ?
          AND k = ?
        ORDER BY e.distance
        """,
        (blob, fetch_k),
    ).fetchall()
    results = [dict(row) for row in rows]
    if exclude_track_id is not None:
        results = [r for r in results if int(r["id"]) != exclude_track_id][:limit]
    return results
