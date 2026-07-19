---
title: Playback module
description: '`claude_dj/playback/port.py` defines the player port and implementations.'
date: '2026-07-18'
tags:
- playback
- spotify
- port
---

`claude_dj/playback/port.py` defines the player port and implementations.

## Types

- `PlayerState` — is_playing, progress/duration, track_id, device
- `PlaybackPort` — `start_block`, `play_uri`, `get_state`
- `FakePlayback` — in-memory multi-URI block for tests
- `SpotifyPlayback` — Connect: multi-URI `start_block`, preferred device, read `/me/player`

## Spotify writes

- `PUT /me/player/play` with full block URIs so Connect skip stays in-plan
- Best-effort shuffle off / repeat off on block start

## Related

- [Virtual queue playback](../concepts/virtual-queue-playback.md)
- [Spotify adapter](spotify-adapter.md)
- [Session](session.md)

[^1]: claude_dj/playback/port.py
