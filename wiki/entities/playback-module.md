---
title: Playback module
description: '`backend/music/playback.py` defines the player port and implementations.'
date: '2026-07-14'
tags:
- playback
- spotify
- port
---

`backend/music/playback.py` defines the player port and implementations.

## Types

- `PlayerState` — is_playing, progress/duration, track_id, device
- `PlaybackPort` — `start_block`, `play_uri`, `get_state`
- `FakePlayback` — in-memory for tests
- `SpotifyPlayback` — Connect: single-URI play, preferred device, read `/me/player`

## Spotify writes

- `start_block`: `PUT /me/player/play` with **all** block `spotify:track:…` URIs (skip-friendly)
- `play_uri`: single URI (escape hatch; force-advance reloads remaining via `start_block`)
- Best-effort shuffle off / repeat off on block start

## Related

- [Virtual queue playback](../concepts/virtual-queue-playback.md)
- [Spotify adapter](spotify-adapter.md)

[^1]: backend/music/playback.py

