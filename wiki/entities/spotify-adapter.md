---
title: Spotify adapter
description: "`claude_dj/adapters/spotify/` \u2014 PKCE auth, catalog reads, player\
  \ control, devices (package fa\xE7ade; logic still in one module)."
date: '2026-07-18'
tags:
- spotify
- oauth
- devices
---

`claude_dj/adapters/spotify/` — PKCE auth, catalog reads, player control, devices (package façade; logic still in one module).

## Auth

Client id: env `SPOTIFY_CLIENT_ID` or `~/.claude-dj/config.json` via `resolve_spotify_client_id()`. Tokens `~/.claude-dj/spotify_tokens.json`. `ensure_session` validates via `/me` or re-login.

## Catalog

`iter_owned_playlists`, `iter_playlist_tracks` via `/playlists/{id}/items`. Also `iter_top_tracks`, `iter_recently_played` for cold-start seeds.

## Playback / devices

- `get_playback_state`, `start_playback_uris`, shuffle/repeat
- `list_devices`, `transfer_playback`
- Preferred device file `~/.claude-dj/device.json`

Scopes include playlist read + playback read/modify + top/recently-played.[^1]

[^1]: claude_dj/adapters/spotify/; claude_dj/config.py
