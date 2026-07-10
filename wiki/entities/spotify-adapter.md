---
title: Spotify Adapter
description: Current responsibilities and boundaries of the Spotify API adapter used by Claude DJ.
date: 2026-07-08
tags: [spotify, adapter, oauth, playback]
---

The Spotify adapter owns low-level Spotify Web API interactions. Higher-level behavior, such as device fallback and playback monitoring, belongs to daemon and device-policy code rather than the adapter itself.[^1][^2][^3]

## Responsibilities

| Area | Current support |
| --- | --- |
| OAuth | PKCE login and token-cache refresh flow. |
| Devices | Fetch visible Spotify Connect devices and normalize them. |
| Playback start | Send `PUT /me/player/play` with an optional device id. |
| Playback state | Fetch current playback state for monitoring. |
| Queue append | Add one Spotify URI to the queue. |
| Playback options | Set repeat mode and shuffle state. |
| Pause/resume | Pause and resume current playback for narration transitions. |
| Playlists | Fetch playlists and playlist items for catalog sync. |

## Boundary

```mermaid
graph LR
    A["Daemon"] --> B["Spotify adapter"]
    C["Device policy"] --> B
    D["Catalog indexing"] --> B
    B --> E["Spotify Web API"]
```

The adapter exposes Spotify-specific operations. The daemon decides when to call them, and `devices.py` decides whether a saved preferred device is eligible for fallback playback.[^2][^3]

## Current Missing Playback Controls

| Control | Status |
| --- | --- |
| Transfer playback | Not implemented. |
| Skip current track | Not implemented. |
| Clear or replace queue | Not available through the current adapter; queueing appends only. |
| Rich user feedback | Not implemented. |

These gaps should stay in [Roadmap](../roadmap.md) until there is code support.

[^1]: spotify.py
[^2]: daemon.py
[^3]: devices.py
