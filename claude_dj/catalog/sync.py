import threading
from datetime import datetime, timezone

from claude_dj.adapters import deezer, spotify
from claude_dj.adapters.deezer import DeezerError
from claude_dj.embeddings import EmbedError, embed_preview
from claude_dj.catalog import db

_lock = threading.Lock()
_syncing = False
_current: dict | None = None


def is_syncing() -> bool:
    return _syncing


def current_track() -> dict | None:
    return _current


def kick() -> bool:
    """Start a background sync if one is not already running. Returns True if started."""
    global _syncing
    with _lock:
        if _syncing:
            return False
        _syncing = True
        thread = threading.Thread(target=_run_safe, daemon=True)
        thread.start()
        return True


def _run_safe() -> None:
    global _syncing, _current
    try:
        run_sync()
    finally:
        _current = None
        with _lock:
            _syncing = False


def run_sync() -> None:
    """Pull owned Spotify playlists, then embed pending tracks one preview at a time."""
    global _current
    conn = db.connect()
    try:
        _pull_catalog(conn)
        db.delete_orphan_tracks(conn)
        work = db.list_tracks(conn, "pending") + db.list_tracks(conn, "retry")
        for track in work:
            _current = {"name": track["name"], "artists": track["artists"]}
            _embed_one(conn, track)
    finally:
        _current = None
        conn.close()


def _pull_catalog(conn) -> None:
    """Refresh owned playlists and membership from Spotify."""
    now = datetime.now(timezone.utc).isoformat()
    for playlist in spotify.iter_owned_playlists():
        spotify_id = playlist["id"]
        snapshot_id = playlist.get("snapshot_id")
        existing = db.get_playlist_by_spotify_id(conn, spotify_id)
        owner_id = (playlist.get("owner") or {}).get("id")
        tracks_total = ((playlist.get("tracks") or {}).get("total"))
        playlist_id = db.upsert_playlist(
            conn,
            spotify_id=spotify_id,
            name=playlist.get("name") or "",
            snapshot_id=snapshot_id,
            owner_spotify_id=owner_id,
            tracks_total=tracks_total,
        )
        if existing and existing.get("snapshot_id") and existing.get("snapshot_id") == snapshot_id:
            continue

        members: list[tuple[int, int | None, str | None]] = []
        for position, item in enumerate(spotify.iter_playlist_tracks(spotify_id)):
            track_id = db.upsert_track(
                conn,
                spotify_id=item["spotify_id"],
                name=item["name"],
                artists=item["artists"] or "Unknown",
                isrc=item.get("isrc"),
                album_name=item.get("album_name"),
                duration_ms=item.get("duration_ms"),
            )
            members.append((track_id, position, item.get("added_at")))
        db.set_playlist_tracks(conn, playlist_id, members)
        db.upsert_playlist(
            conn,
            spotify_id=spotify_id,
            name=playlist.get("name") or "",
            snapshot_id=snapshot_id,
            owner_spotify_id=owner_id,
            tracks_total=tracks_total,
            synced_at=now,
        )


def _embed_one(conn, track: dict) -> None:
    """Download one Deezer preview, embed it, and update track status."""
    track_id = int(track["id"])
    isrc = track.get("isrc")
    if not isrc:
        db.set_status(conn, track_id, "skipped")
        return
    try:
        hit = deezer.lookup_by_isrc(isrc)
    except DeezerError:
        db.set_status(conn, track_id, "retry")
        return
    if not hit or not hit.get("preview"):
        db.set_status(conn, track_id, "skipped")
        return
    conn.execute(
        """
        UPDATE tracks
        SET deezer_id = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (hit["id"], track_id),
    )
    conn.commit()
    try:
        vector = embed_preview(hit["preview"])
        db.upsert_embedding(conn, track_id, vector)
    except EmbedError:
        db.set_status(conn, track_id, "retry")
