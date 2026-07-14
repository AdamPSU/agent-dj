---
title: Local storage
description: Claude DJ persists catalog data under `~/.claude-dj/` using **SQLite**
  with the **sqlite-vec** extension for 512-d nearest-neighbor search.
date: '2026-07-14'
tags:
- sqlite
- sqlite-vec
- storage
- schema
---

Claude DJ persists catalog data under `~/.claude-dj/` using **SQLite** with the **sqlite-vec** extension for 512-d nearest-neighbor search.

## Paths

| Path | Contents |
|------|----------|
| `~/.claude-dj/catalog.db` | Playlists, tracks, membership, embeddings |
| `~/.claude-dj/spotify_tokens.json` | OAuth tokens (mode 600) — not in the DB |

Configured in `backend/config.py` as `APP_DIR`, `DB_PATH`, `SPOTIFY_TOKEN_PATH`.[^1]

## Schema (logical)

| Table | Purpose |
|-------|---------|
| `playlists` | Spotify playlist id, name, snapshot, owner, totals, synced_at |
| `tracks` | Spotify id, ISRC, metadata, deezer_id, **status** |
| `playlist_tracks` | Membership, position, added_at |
| `track_embeddings` | vec0 virtual table: `track_id` + `embedding float[512]` |

Track statuses: `pending` \| `indexed` \| `skipped` \| `retry`.[^2]

## Key operations

- Upsert playlist/track; replace membership for a playlist
- `upsert_embedding` → marks track `indexed`
- `similar_tracks(vector, limit, exclude_track_id?)` for k-NN
- `get_embedding` / `list_indexed_track_ids` / `count_indexed` for recommend
- `delete_orphan_tracks` after catalog pull

## Related

- [Catalog database](../entities/catalog-database.md)
- [Catalog sync](catalog-sync.md)
- [Recommendation blocks](recommendation-blocks.md)

[^1]: backend/config.py
[^2]: backend/storage/db.py

