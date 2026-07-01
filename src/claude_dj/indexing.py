"""Catalog indexing orchestration for Claude DJ."""

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import urllib.request

from claude_dj.adapters.spotify import (
    SpotifyAPIAuthError,
    SpotifyAPIForbiddenError,
    SpotifyAuthError,
    fetch_all_playlists,
    fetch_playlist_tracks_with_skipped_count,
    load_token,
    refresh_access_token,
)
from claude_dj.config import MissingConfigError, SpotifyConfig, get_spotify_config, get_spotify_token_file
from claude_dj.storage.db import (
    CatalogStatus,
    get_catalog_status,
    replace_source_tracks,
    upsert_source,
    upsert_track,
)


@dataclass(frozen=True)
class IndexSummary:
    """Summary of a Spotify catalog indexing pass."""

    playlist_count: int
    track_count: int
    skipped_track_count: int
    catalog_status: CatalogStatus

    def to_json(self) -> dict[str, int | bool]:
        """Serialize the indexing summary for daemon responses."""
        return {
            "ran": True,
            "playlist_count": self.playlist_count,
            "track_count": self.track_count,
            "skipped_track_count": self.skipped_track_count,
        }


class SpotifyIndexingAuthRequired(RuntimeError):
    """Raised when indexing cannot run until the user logs into Spotify again."""


class SpotifyIndexingAccessDenied(RuntimeError):
    """Raised when Spotify refuses playlist metadata access for this app/user."""


def index_spotify_playlists(
    db: sqlite3.Connection,
    *,
    token_file: Path | None = None,
    config: SpotifyConfig | None = None,
    urlopen=urllib.request.urlopen,
) -> IndexSummary:
    """Index all Spotify playlists visible to the authenticated user."""
    resolved_token_file = token_file or get_spotify_token_file()
    try:
        token = load_token(resolved_token_file)
    except SpotifyAuthError as exc:
        raise SpotifyIndexingAuthRequired(str(exc)) from exc

    access_token = str(token["access_token"])
    try:
        return _index_with_access_token(db, access_token=access_token, urlopen=urlopen)
    except SpotifyAPIForbiddenError as exc:
        raise SpotifyIndexingAccessDenied("Spotify denied playlist track access.") from exc
    except SpotifyAPIAuthError:
        refreshed_token = _refresh_for_indexing(
            config=config,
            token_file=resolved_token_file,
            token=token,
            urlopen=urlopen,
        )
        try:
            return _index_with_access_token(
                db,
                access_token=str(refreshed_token["access_token"]),
                urlopen=urlopen,
            )
        except SpotifyAPIForbiddenError as exc:
            raise SpotifyIndexingAccessDenied("Spotify denied playlist track access.") from exc


def _refresh_for_indexing(
    *,
    config: SpotifyConfig | None,
    token_file: Path,
    token: dict[str, object],
    urlopen,
) -> dict[str, object]:
    try:
        resolved_config = config or get_spotify_config()
        return refresh_access_token(
            config=resolved_config,
            token_file=token_file,
            token=token,
            urlopen=urlopen,
        )
    except (MissingConfigError, SpotifyAuthError) as exc:
        raise SpotifyIndexingAuthRequired("Spotify login expired. Run spotify-login again.") from exc


def _index_with_access_token(
    db: sqlite3.Connection,
    *,
    access_token: str,
    urlopen,
) -> IndexSummary:
    playlists = fetch_all_playlists(access_token, urlopen=urlopen)
    unique_track_ids: set[int] = set()
    skipped_track_count = 0

    for playlist in playlists:
        source_row_id = upsert_source(
            db,
            source_type="spotify_playlist",
            source_id=playlist.id,
            name=playlist.name,
            description=playlist.description,
        )
        playlist_tracks, skipped_count = fetch_playlist_tracks_with_skipped_count(
            access_token,
            playlist.id,
            urlopen=urlopen,
        )
        skipped_track_count += skipped_count
        memberships: list[tuple[int, int, str | None]] = []
        for playlist_track in playlist_tracks:
            track = playlist_track.track
            track_row_id = upsert_track(
                db,
                spotify_track_id=track.spotify_track_id,
                spotify_uri=track.spotify_uri,
                isrc=track.isrc,
                title=track.title,
                artist_name=track.artist_name,
                album_name=track.album_name,
                duration_ms=track.duration_ms,
                explicit=track.explicit,
                popularity=track.popularity,
            )
            unique_track_ids.add(track_row_id)
            memberships.append((track_row_id, playlist_track.position, playlist_track.added_at))
        replace_source_tracks(db, source_row_id, memberships)

    db.commit()
    return IndexSummary(
        playlist_count=len(playlists),
        track_count=len(unique_track_ids),
        skipped_track_count=skipped_track_count,
        catalog_status=get_catalog_status(db),
    )
