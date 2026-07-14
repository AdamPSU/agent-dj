---
title: Virtual queue playback
description: Playback treats Spotify as a **dumb speaker**. The app owns a **virtual
  queue** of planned tracks; Spotify only receives single-track play commands and
  is polled for state.
date: '2026-07-14'
tags:
- playback
- virtual-queue
- spotify
- monitor
---

Playback treats Spotify as a **dumb speaker**. The app owns a **virtual queue** of planned tracks; Spotify only receives single-track play commands and is polled for state.

## Why

- No reliable clear/remove on Spotify’s native queue
- No playback webhooks → must poll `GET /me/player`
- Users can skip or play foreign tracks anytime

## Modes

| Mode | Meaning |
|------|---------|
| `idle` | Not DJing |
| `attached` | Controlling; monitor ticks |
| `yielded` | Saw foreign track; stopped injecting until `/play` again |

## Flow

```mermaid
flowchart TD
  Play["/play"] --> Mint["recommend_block"]
  Mint --> VQ["virtual_queue"]
  VQ --> One["play first URI"]
  One --> Mon["monitor poll 3-5s"]
  Mon --> Same{"same expected id?"}
  Same -->|yes near end| Next["play next planned"]
  Same -->|planned other| Recon["move cursor"]
  Same -->|foreign| Yield["mode yielded"]
  Next --> Empty{"queue empty?"}
  Empty -->|yes| Mint2["mint next block"]
```

## Skip behavior

- Skip **within** block → reconcile cursor, stay attached  
- Skip/land **outside** plan → yield  
- Natural end (~last 5s) → play next planned URI  

## Device targeting

Preferred id from `~/.claude-dj/device.json` if set; else Spotify active device. List/select via `claude-dj device`.[^1]

## Related

- [Orchestrator](../entities/orchestrator.md)
- [Playback module](../entities/playback-module.md)
- [Recommendation blocks](recommendation-blocks.md)

[^1]: backend/adapters/spotify.py; backend/music/playback.py; backend/orchestrator.py

