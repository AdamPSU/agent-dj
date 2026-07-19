---
title: Virtual queue playback
description: Playback treats Spotify as a **dumb speaker**. The app owns a **virtual
  queue** of planned tracks; Spotify receives multi-URI blocks and is polled for state.
date: '2026-07-18'
tags:
- playback
- virtual-queue
- spotify
- monitor
---

Playback treats Spotify as a **dumb speaker**. The app owns a **virtual queue** of planned tracks; Spotify receives multi-URI blocks and is polled for state.

## Why

- No reliable clear/remove on Spotify’s native queue
- No playback webhooks → poll `GET /me/player`
- Users can skip or play foreign tracks anytime

## Modes

| Mode | Meaning |
|------|---------|
| `idle` | Not DJing |
| `attached` | Controlling; monitor ticks |

Foreign track → stop daemon via monitor (not a long-lived “yielded” mode).

## Flow

```mermaid
flowchart TD
  Jam["/jam"] --> Mint["mint block A + B"]
  Mint --> VQ["plan + start_block URIs"]
  VQ --> Mon["monitor poll ~1s"]
  Mon --> Same{"same expected id?"}
  Same -->|yes in first block| Wait["ok"]
  Same -->|entered last block| Mint1["mint one more block"]
  Same -->|planned other| Recon["move cursor"]
  Same -->|foreign| Kill["stop daemon"]
```

## Buffer rule

Always keep **two blocks** loaded when possible: cold jam mints two; when the cursor enters the last loaded block, mint exactly one more. Pause never mints.

## Device targeting

Preferred id from `~/.claude-dj/device.json` if set; else Spotify active device. Set during `dj setup` or `dj device`.[^1]

## Related

- [Session](../entities/session.md)
- [Playback module](../entities/playback-module.md)
- [Recommendation blocks](recommendation-blocks.md)

[^1]: claude_dj/adapters/spotify/; claude_dj/playback/port.py; claude_dj/session/
