---
title: Catalog sync
description: Catalog sync turns **owned Spotify playlists** into a local searchable
  catalog with embeddings (`claude_dj/catalog/sync.py`).
date: '2026-07-18'
tags:
- sync
- catalog
- pipeline
- embeddings
---

Catalog sync turns **owned Spotify playlists** into a local searchable catalog with embeddings (`claude_dj/catalog/sync.py`).

## Trigger

- `POST /play` and `POST /sync` both call `catalog_sync.kick()`.[^1]
- `kick()` starts at most one background thread (single-flight).[^2]

## Pipeline

```mermaid
flowchart TD
  Kick["kick"] --> Pull["Pull owned playlists"]
  Pull --> Members["Upsert tracks + playlist membership"]
  Members --> Orphans["Delete orphan tracks"]
  Orphans --> Work["pending + retry tracks"]
  Work --> One["For each track"]
  One --> ISRC{"Has ISRC?"}
  ISRC -->|no| Skip["status skipped"]
  ISRC -->|yes| Deezer["Deezer lookup_by_isrc"]
  Deezer -->|error| Retry["status retry"]
  Deezer -->|no preview| Skip
  Deezer -->|preview| Emb["embed_preview MuQ"]
  Emb -->|fail| Retry
  Emb -->|ok| Indexed["upsert_embedding indexed"]
```

## Rules

| Rule | Detail |
|------|--------|
| Owned only | Playlist `owner.id == /me.id` |
| Snapshot skip | Unchanged `snapshot_id` skips re-fetch |
| Sequential embed | One preview → embed at a time |
| Statuses | `pending` → `indexed` \| `skipped` \| `retry` |

## Progress

`/status` exposes `syncing`, indexed counts, `now_playing` for CLI and statusline.[^1]

## Related

- [Spotify adapter](../entities/spotify-adapter.md)
- [Deezer adapter](../entities/deezer-adapter.md)
- [MuQ embeddings](../entities/muq-embeddings.md)
- [Local storage](local-storage.md)

[^1]: claude_dj/daemon/server.py
[^2]: claude_dj/catalog/sync.py
