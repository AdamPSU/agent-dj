"""SQLite persistence for Claude DJ.

This module owns tracks, previews, embeddings, and playlist membership storage.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import array
import sqlite3

import sqlite_vec


EMBEDDING_DIMENSIONS = 1024


@dataclass(frozen=True)
class CatalogStatus:
    """Summary of local catalog/index readiness."""

    source_count: int
    track_count: int
    embedding_count: int
    preview_match_count: int = 0
    preview_pending_count: int | None = None
    embedding_pending_count: int | None = None

    @property
    def needs_spotify_index(self) -> bool:
        """Return whether Spotify playlist metadata still needs indexing."""
        return self.source_count == 0 or self.track_count == 0

    @property
    def needs_preview_resolution(self) -> bool:
        """Return whether indexed tracks still need preview matching."""
        return self.track_count > 0 and self._preview_pending_count() > 0

    @property
    def needs_embeddings(self) -> bool:
        """Return whether indexed tracks still need local audio embeddings."""
        return self._embedding_pending_count() > 0

    @property
    def needs_onboarding(self) -> bool:
        """Return whether any catalog-building phase still needs work."""
        return self.needs_spotify_index or self.needs_preview_resolution or self.needs_embeddings

    def to_json(self) -> dict[str, int | bool]:
        """Serialize catalog status for daemon responses."""
        return {
            "source_count": self.source_count,
            "track_count": self.track_count,
            "preview_match_count": self.preview_match_count,
            "preview_pending_count": self._preview_pending_count(),
            "embedding_count": self.embedding_count,
            "embedding_pending_count": self._embedding_pending_count(),
            "needs_spotify_index": self.needs_spotify_index,
            "needs_preview_resolution": self.needs_preview_resolution,
            "needs_embeddings": self.needs_embeddings,
            "needs_onboarding": self.needs_onboarding,
        }

    def _preview_pending_count(self) -> int:
        if self.preview_pending_count is not None:
            return self.preview_pending_count
        return max(self.track_count - self.preview_match_count, 0)

    def _embedding_pending_count(self) -> int:
        if self.embedding_pending_count is not None:
            return self.embedding_pending_count
        return 0


@dataclass(frozen=True)
class TrackPreviewCandidate:
    """Track row that still needs preview resolution."""

    track_id: int
    isrc: str | None


@dataclass(frozen=True)
class TrackEmbeddingCandidate:
    """Matched preview row that still needs a local audio embedding."""

    track_id: int
    preview_url: str


@dataclass(frozen=True)
class PlayableTrack:
    """Track metadata needed to start Spotify playback."""

    track_id: int
    spotify_uri: str
    title: str
    artist_name: str


@dataclass(frozen=True)
class PlaylistSourceCandidate:
    """Playlist source that has embedded tracks available for DJ selection."""

    source_id: int


@dataclass(frozen=True)
class EmbeddedTrackCandidate:
    """Embedded track id available for DJ selection."""

    track_id: int


def connect(database_file: Path) -> sqlite3.Connection:
    """Open SQLite and load sqlite-vec for vector search."""
    database_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(database_file)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def initialize_schema(
    db: sqlite3.Connection,
    dimensions: int = EMBEDDING_DIMENSIONS,
    *,
    model_name: str | None = None,
    model_version: str | None = None,
) -> None:
    """Create the initial metadata and vector-search schema if needed."""
    _drop_embedding_tables_if_incompatible(db, dimensions, model_name, model_version)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS tracks (
          id INTEGER PRIMARY KEY,
          spotify_track_id TEXT NOT NULL UNIQUE,
          spotify_uri TEXT NOT NULL,
          isrc TEXT,
          title TEXT NOT NULL,
          artist_name TEXT NOT NULL,
          album_name TEXT,
          duration_ms INTEGER,
          explicit INTEGER NOT NULL DEFAULT 0,
          popularity INTEGER,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_tracks_isrc ON tracks(isrc);
        CREATE INDEX IF NOT EXISTS idx_tracks_artist_title ON tracks(artist_name, title);

        CREATE TABLE IF NOT EXISTS sources (
          id INTEGER PRIMARY KEY,
          source_type TEXT NOT NULL,
          source_id TEXT NOT NULL,
          name TEXT NOT NULL,
          description TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(source_type, source_id)
        );

        CREATE TABLE IF NOT EXISTS source_tracks (
          source_id INTEGER NOT NULL,
          track_id INTEGER NOT NULL,
          position INTEGER,
          added_at TEXT,
          PRIMARY KEY (source_id, track_id),
          FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
          FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS preview_matches (
          id INTEGER PRIMARY KEY,
          track_id INTEGER NOT NULL UNIQUE,
          provider TEXT NOT NULL,
          provider_track_id TEXT,
          preview_url TEXT,
          match_method TEXT NOT NULL,
          status TEXT NOT NULL,
          failure_reason TEXT,
          resolved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS embedding_metadata (
          track_id INTEGER PRIMARY KEY,
          model_name TEXT NOT NULL,
          model_version TEXT,
          dimensions INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
        );

        """
    )
    db.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS track_embeddings USING vec0(track_id INTEGER PRIMARY KEY, embedding FLOAT[{dimensions}])"
    )
    db.commit()


def get_catalog_status(db: sqlite3.Connection) -> CatalogStatus:
    """Return counts that tell the daemon whether onboarding is needed."""
    return CatalogStatus(
        source_count=_count(db, "sources"),
        track_count=_count(db, "tracks"),
        preview_match_count=_count(db, "preview_matches"),
        preview_pending_count=_preview_pending_count(db),
        embedding_count=_count(db, "track_embeddings"),
        embedding_pending_count=_embedding_pending_count(db),
    )


def upsert_source(
    db: sqlite3.Connection,
    *,
    source_type: str,
    source_id: str,
    name: str,
    description: str | None,
) -> int:
    """Insert or update a catalog source and return its row id."""
    db.execute(
        """
        INSERT INTO sources (source_type, source_id, name, description)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(source_type, source_id) DO UPDATE SET
          name = excluded.name,
          description = excluded.description,
          updated_at = CURRENT_TIMESTAMP
        """,
        (source_type, source_id, name, description),
    )
    row = db.execute(
        "SELECT id FROM sources WHERE source_type = ? AND source_id = ?",
        (source_type, source_id),
    ).fetchone()
    return int(row["id"])


def upsert_track(
    db: sqlite3.Connection,
    *,
    spotify_track_id: str,
    spotify_uri: str,
    isrc: str | None,
    title: str,
    artist_name: str,
    album_name: str | None,
    duration_ms: int | None,
    explicit: bool,
    popularity: int | None,
) -> int:
    """Insert or update a Spotify track and return its row id."""
    db.execute(
        """
        INSERT INTO tracks (
          spotify_track_id,
          spotify_uri,
          isrc,
          title,
          artist_name,
          album_name,
          duration_ms,
          explicit,
          popularity
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(spotify_track_id) DO UPDATE SET
          spotify_uri = excluded.spotify_uri,
          isrc = excluded.isrc,
          title = excluded.title,
          artist_name = excluded.artist_name,
          album_name = excluded.album_name,
          duration_ms = excluded.duration_ms,
          explicit = excluded.explicit,
          popularity = excluded.popularity,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            spotify_track_id,
            spotify_uri,
            isrc,
            title,
            artist_name,
            album_name,
            duration_ms,
            int(explicit),
            popularity,
        ),
    )
    row = db.execute(
        "SELECT id FROM tracks WHERE spotify_track_id = ?",
        (spotify_track_id,),
    ).fetchone()
    return int(row["id"])


def replace_source_tracks(
    db: sqlite3.Connection,
    source_id: int,
    memberships: list[tuple[int, int, str | None]],
) -> None:
    """Replace track memberships for a source with the latest playlist ordering."""
    db.execute("DELETE FROM source_tracks WHERE source_id = ?", (source_id,))
    db.executemany(
        """
        INSERT OR REPLACE INTO source_tracks (source_id, track_id, position, added_at)
        VALUES (?, ?, ?, ?)
        """,
        [(source_id, track_id, position, added_at) for track_id, position, added_at in memberships],
    )


def fetch_tracks_needing_preview_resolution(
    db: sqlite3.Connection,
    *,
    limit: int | None = None,
) -> list[TrackPreviewCandidate]:
    """Return tracks without a cached preview-match row."""
    query = """
        SELECT tracks.id, tracks.isrc
        FROM tracks
        LEFT JOIN preview_matches ON preview_matches.track_id = tracks.id
        LEFT JOIN track_embeddings ON track_embeddings.track_id = tracks.id
        WHERE preview_matches.id IS NULL
           OR (
             preview_matches.status = 'matched'
             AND preview_matches.preview_url IS NOT NULL
             AND preview_matches.preview_url != ''
             AND track_embeddings.track_id IS NULL
           )
        ORDER BY tracks.id
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)
    rows = db.execute(query, params).fetchall()
    return [
        TrackPreviewCandidate(
            track_id=int(row["id"]),
            isrc=row["isrc"] if isinstance(row["isrc"], str) and row["isrc"] else None,
        )
        for row in rows
    ]


def fetch_tracks_needing_embeddings(
    db: sqlite3.Connection,
    *,
    limit: int | None = None,
) -> list[TrackEmbeddingCandidate]:
    """Return matched preview URLs without a cached embedding row."""
    query = """
        SELECT tracks.id, preview_matches.preview_url
        FROM tracks
        JOIN preview_matches ON preview_matches.track_id = tracks.id
        LEFT JOIN track_embeddings ON track_embeddings.track_id = tracks.id
        WHERE preview_matches.status = 'matched'
          AND preview_matches.preview_url IS NOT NULL
          AND preview_matches.preview_url != ''
          AND track_embeddings.track_id IS NULL
        ORDER BY tracks.id
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)
    rows = db.execute(query, params).fetchall()
    return [
        TrackEmbeddingCandidate(
            track_id=int(row["id"]),
            preview_url=str(row["preview_url"]),
        )
        for row in rows
    ]


def fetch_tracks_by_ids(db: sqlite3.Connection, track_ids: Sequence[int]) -> list[PlayableTrack]:
    """Return playable Spotify track metadata in the requested track-id order."""
    if not track_ids:
        return []

    unique_track_ids = list(dict.fromkeys(track_ids))
    placeholders = ", ".join("?" for _ in unique_track_ids)
    rows = db.execute(
        f"""
        SELECT id, spotify_uri, title, artist_name
        FROM tracks
        WHERE id IN ({placeholders})
          AND spotify_uri IS NOT NULL
          AND spotify_uri != ''
        """,
        unique_track_ids,
    ).fetchall()
    tracks_by_id = {
        int(row["id"]): PlayableTrack(
            track_id=int(row["id"]),
            spotify_uri=str(row["spotify_uri"]),
            title=str(row["title"]),
            artist_name=str(row["artist_name"]),
        )
        for row in rows
    }
    return [tracks_by_id[track_id] for track_id in unique_track_ids if track_id in tracks_by_id]


def fetch_embedded_track_ids(db: sqlite3.Connection) -> set[int]:
    """Return all tracks with locally stored audio embeddings."""
    rows = db.execute("SELECT track_id FROM track_embeddings").fetchall()
    return {int(row["track_id"]) for row in rows}


def fetch_playlist_sources_with_embedded_tracks(
    db: sqlite3.Connection,
    *,
    excluded_track_ids: set[int] | None = None,
) -> list[PlaylistSourceCandidate]:
    """Return playlist sources that can provide at least one embedded seed track."""
    excluded = excluded_track_ids or set()
    query = """
        SELECT DISTINCT sources.id
        FROM sources
        JOIN source_tracks ON source_tracks.source_id = sources.id
        JOIN track_embeddings ON track_embeddings.track_id = source_tracks.track_id
        WHERE sources.source_type = 'spotify_playlist'
    """
    params: list[int] = []
    if excluded:
        placeholders = ", ".join("?" for _ in excluded)
        query += f" AND source_tracks.track_id NOT IN ({placeholders})"
        params.extend(sorted(excluded))
    query += " ORDER BY sources.id"
    rows = db.execute(query, params).fetchall()
    return [PlaylistSourceCandidate(source_id=int(row["id"])) for row in rows]


def fetch_embedded_tracks_for_source(
    db: sqlite3.Connection,
    *,
    source_id: int,
    excluded_track_ids: set[int] | None = None,
) -> list[EmbeddedTrackCandidate]:
    """Return embedded tracks that belong to one playlist source."""
    excluded = excluded_track_ids or set()
    query = """
        SELECT source_tracks.track_id
        FROM source_tracks
        JOIN track_embeddings ON track_embeddings.track_id = source_tracks.track_id
        WHERE source_tracks.source_id = ?
    """
    params: list[int] = [source_id]
    if excluded:
        placeholders = ", ".join("?" for _ in excluded)
        query += f" AND source_tracks.track_id NOT IN ({placeholders})"
        params.extend(sorted(excluded))
    query += " ORDER BY source_tracks.position, source_tracks.track_id"
    rows = db.execute(query, params).fetchall()
    return [EmbeddedTrackCandidate(track_id=int(row["track_id"])) for row in rows]


def upsert_track_embedding(
    db: sqlite3.Connection,
    *,
    track_id: int,
    embedding: Sequence[float],
    model_name: str,
    model_version: str | None,
    dimensions: int = EMBEDDING_DIMENSIONS,
) -> None:
    """Insert or replace a local audio embedding and its model metadata."""
    if len(embedding) != dimensions:
        raise ValueError(f"Embedding must contain {dimensions} floats.")

    db.execute(
        "INSERT OR REPLACE INTO track_embeddings (track_id, embedding) VALUES (?, ?)",
        (track_id, array.array("f", embedding).tobytes()),
    )
    db.execute(
        """
        INSERT INTO embedding_metadata (track_id, model_name, model_version, dimensions)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(track_id) DO UPDATE SET
          model_name = excluded.model_name,
          model_version = excluded.model_version,
          dimensions = excluded.dimensions,
          created_at = CURRENT_TIMESTAMP
        """,
        (track_id, model_name, model_version, dimensions),
    )


def upsert_preview_match(
    db: sqlite3.Connection,
    *,
    track_id: int,
    provider: str,
    provider_track_id: str | None,
    preview_url: str | None,
    match_method: str,
    status: str,
    failure_reason: str | None,
) -> None:
    """Insert or update a preview resolution result for a track."""
    db.execute(
        """
        INSERT INTO preview_matches (
          track_id,
          provider,
          provider_track_id,
          preview_url,
          match_method,
          status,
          failure_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(track_id) DO UPDATE SET
          provider = excluded.provider,
          provider_track_id = excluded.provider_track_id,
          preview_url = excluded.preview_url,
          match_method = excluded.match_method,
          status = excluded.status,
          failure_reason = excluded.failure_reason,
          resolved_at = CURRENT_TIMESTAMP
        """,
        (
            track_id,
            provider,
            provider_track_id,
            preview_url,
            match_method,
            status,
            failure_reason,
        ),
    )


def _count(db: sqlite3.Connection, table: str) -> int:
    row = db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"])


def _preview_pending_count(db: sqlite3.Connection) -> int:
    row = db.execute(
        """
        SELECT COUNT(*) AS count
        FROM tracks
        LEFT JOIN preview_matches ON preview_matches.track_id = tracks.id
        WHERE preview_matches.id IS NULL
        """
    ).fetchone()
    return int(row["count"])


def _embedding_pending_count(db: sqlite3.Connection) -> int:
    row = db.execute(
        """
        SELECT COUNT(*) AS count
        FROM preview_matches
        LEFT JOIN track_embeddings ON track_embeddings.track_id = preview_matches.track_id
        WHERE preview_matches.status = 'matched'
          AND preview_matches.preview_url IS NOT NULL
          AND preview_matches.preview_url != ''
          AND track_embeddings.track_id IS NULL
        """
    ).fetchone()
    return int(row["count"])


def _drop_embedding_tables_if_incompatible(
    db: sqlite3.Connection,
    dimensions: int,
    model_name: str | None,
    model_version: str | None,
) -> None:
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'track_embeddings'"
    ).fetchone()
    if row is None:
        return

    sql = str(row["sql"] or "")
    if f"FLOAT[{dimensions}]" not in sql:
        _drop_embedding_tables(db)
        return

    if model_name is None:
        return

    metadata_table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'embedding_metadata'"
    ).fetchone()
    if metadata_table is None:
        _drop_embedding_tables(db)
        return

    rows = db.execute(
        "SELECT model_name, model_version, dimensions FROM embedding_metadata"
    ).fetchall()
    for metadata in rows:
        if (
            metadata["model_name"] != model_name
            or metadata["model_version"] != model_version
            or int(metadata["dimensions"]) != dimensions
        ):
            _drop_embedding_tables(db)
            return


def _drop_embedding_tables(db: sqlite3.Connection) -> None:
    db.execute("DROP TABLE IF EXISTS track_embeddings")
    db.execute("DROP TABLE IF EXISTS embedding_metadata")
