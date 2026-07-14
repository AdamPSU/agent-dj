---
title: Catalog database
description: '`backend/storage/db.py` is the SQLite access layer; `backend/config.py`
  defines paths and Spotify constants.'
date: '2026-07-14'
tags:
- database
- config
- sqlite
---

`backend/storage/db.py` is the SQLite access layer; `backend/config.py` defines paths and Spotify constants.

## Config highlights

| Symbol | Value |
|--------|--------|
| `HOST` / `PORT` | `127.0.0.1` / `8787` |
| `APP_DIR` | `~/.claude-dj` |
| `DB_PATH` | `~/.claude-dj/catalog.db` |
| `SPOTIFY_TOKEN_PATH` | `~/.claude-dj/spotify_tokens.json` |
| `SPOTIFY_CLIENT_ID` | from env |

## DB helpers (selected)

- Schema init + sqlite-vec load on `connect`
- Playlist/track upserts, membership replace
- Embedding serialize/deserialize f32, `upsert_embedding`, `get_embedding`
- `similar_tracks`, `count_indexed`, `list_indexed_track_ids`
- Orphan deletion, status counts

## Related

- [Local storage](../concepts/local-storage.md)
- [Catalog sync](../concepts/catalog-sync.md)

[^1]: backend/storage/db.py; backend/config.py

