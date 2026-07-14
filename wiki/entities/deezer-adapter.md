---
title: Deezer adapter
description: '`backend/adapters/deezer.py` maps a track **ISRC** to a short **preview
  URL** for embedding. No auth.'
date: '2026-07-14'
tags:
- deezer
- isrc
- preview
---

`backend/adapters/deezer.py` maps a track **ISRC** to a short **preview URL** for embedding. No auth.

## API

`lookup_by_isrc(isrc) -> dict | None`

Returns `id`, `title`, `artist`, `isrc`, `preview`, `readable`, `duration`. HTTP 404 or error payload → `None`; network/HTTP failures raise `DeezerError` (sync marks `retry`).[^1]

## Role in pipeline

Spotify provides ISRC → Deezer provides ~30s MP3 preview → MuQ embeds preview audio. No full-track download.

## Related

- [Catalog sync](../concepts/catalog-sync.md)
- [MuQ embeddings](muq-embeddings.md)

[^1]: backend/adapters/deezer.py; backend/sync.py

