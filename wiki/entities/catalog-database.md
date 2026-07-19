---
title: Catalog database
description: '`claude_dj/catalog/db.py` is the SQLite access layer; `claude_dj/config.py`
  defines paths and Spotify constants.'
date: '2026-07-18'
tags:
- database
- config
- sqlite
---

`claude_dj/catalog/db.py` is the SQLite access layer; `claude_dj/config.py` defines paths and Spotify constants.

## Config highlights

| Symbol | Value |
|--------|--------|
| `HOST` / `PORT` | `127.0.0.1` / `8787` |
| `APP_DIR` | `~/.claude-dj` |
| `DB_PATH` | `~/.claude-dj/catalog.db` |
| `CONFIG_PATH` | `~/.claude-dj/config.json` |
| `SPOTIFY_TOKEN_PATH` | `~/.claude-dj/spotify_tokens.json` |
| Client ID | `resolve_spotify_client_id()` — env then config file |

## DB helpers (selected)

- Schema init + sqlite-vec load on `connect`
- Playlist/track upserts, membership replace
- Embedding serialize/deserialize f32, `upsert_embedding`, `get_embedding`
- `similar_tracks`, `count_indexed`, `list_indexed_track_ids`
- Orphan deletion, status counts

## Related

- [Local storage](../concepts/local-storage.md)
- [Catalog sync](../concepts/catalog-sync.md)

[^1]: claude_dj/catalog/db.py; claude_dj/config.py
