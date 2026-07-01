"""SQLite persistence for Claude DJ.

This module will own sessions, tracks, previews, embeddings, and decision history storage.
"""

from dataclasses import dataclass
from pathlib import Path
import sqlite3

import sqlite_vec


EMBEDDING_DIMENSIONS = 4


@dataclass(frozen=True)
class CatalogStatus:
    """Summary of local catalog/index readiness."""

    source_count: int
    track_count: int
    embedding_count: int

    @property
    def needs_onboarding(self) -> bool:
        """Return whether the user's Spotify playlists still need indexing."""
        return self.source_count == 0 or self.track_count == 0 or self.embedding_count == 0

    def to_json(self) -> dict[str, int | bool]:
        """Serialize catalog status for daemon responses."""
        return {
            "source_count": self.source_count,
            "track_count": self.track_count,
            "embedding_count": self.embedding_count,
            "needs_onboarding": self.needs_onboarding,
        }


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


def initialize_schema(db: sqlite3.Connection, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
    """Create the initial metadata and vector-search schema if needed."""
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
          confidence REAL NOT NULL,
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
        embedding_count=_count(db, "track_embeddings"),
    )


def _count(db: sqlite3.Connection, table: str) -> int:
    row = db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"])
