---
title: Spotify adapter
description: "`backend/adapters/spotify.py` \u2014 PKCE auth, catalog reads, player\
  \ control, devices."
date: '2026-07-14'
tags:
- spotify
- oauth
- devices
---

`backend/adapters/spotify.py` — PKCE auth, catalog reads, player control, devices.

## Auth

Client id env `SPOTIFY_CLIENT_ID`; tokens `~/.claude-dj/spotify_tokens.json`. `ensure_session` validates via `/me` or re-login.

## Catalog

`iter_owned_playlists`, `iter_playlist_tracks` via `/playlists/{id}/items`.

## Playback / devices

- `get_playback_state`, `start_playback_uris`, shuffle/repeat
- `list_devices`, `transfer_playback`
- Preferred device file `~/.claude-dj/device.json`

Scopes include playlist read + playback read/modify.[^1]

[^1]: backend/adapters/spotify.py; backend/config.py

