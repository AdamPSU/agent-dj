---
title: Local storage
description: Claude DJ persists data under `~/.claude-dj/` using **SQLite** + **sqlite-vec**
  (512-d) for catalog embeddings, plus small JSON files for auth and prefs.
date: '2026-07-18'
tags:
- sqlite
- sqlite-vec
- storage
- schema
- config
---

Claude DJ persists data under `~/.claude-dj/` using **SQLite** + **sqlite-vec** (512-d) for catalog embeddings, plus small JSON files for auth and prefs.

## Paths

| Path | Contents |
|------|----------|
| `~/.claude-dj/config.json` | Spotify client ID (mode 600) |
| `~/.claude-dj/catalog.db` | Playlists, tracks, membership, embeddings |
| `~/.claude-dj/spotify_tokens.json` | OAuth tokens (mode 600) |
| `~/.claude-dj/device.json` | Preferred Connect device id |
| `~/.claude-dj/statusline.json` | Statusline install marker |
| `~/.claude-dj/daemon.log` | Daemon stdout/stderr |

Configured in `claude_dj/config.py`. Client ID resolution: env `SPOTIFY_CLIENT_ID` if set, else `config.json`.[^1]

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
- `similar_tracks` for k-NN
- `get_embedding` / `list_indexed_track_ids` / `count_indexed` for recommend
- `delete_orphan_tracks` after catalog pull

## Related

- [Catalog database](../entities/catalog-database.md)
- [Catalog sync](catalog-sync.md)
- [claude-dj CLI](../entities/claude-dj-cli.md)

[^1]: claude_dj/config.py
[^2]: claude_dj/catalog/db.py
