---
title: Daemon
description: Long-lived FastAPI + uvicorn on `127.0.0.1:8787` (`claude_dj/daemon/server.py`).
date: '2026-07-18'
tags:
- daemon
- fastapi
---

Long-lived FastAPI + uvicorn on `127.0.0.1:8787` (`claude_dj/daemon/server.py`).

## Routes

| Method | Path | Role |
|--------|------|------|
| GET | `/status` | Sync + session snapshot |
| POST | `/play` | Kick sync, ensure monitor, `Session.play` |
| POST | `/sync` | Kick catalog sync |
| GET | `/devices` | List Connect devices + preferred id |
| POST | `/devices/{id}` | Save preferred device + transfer |
| POST | `/quit` | Stop monitor + uvicorn |

## Background

- Catalog sync thread (`catalog.sync.kick`)
- DJ monitor thread (~1s) while mode `attached`
- Playback: `SpotifyPlayback` (tokens via setup/login)

## Related

- [Session](session.md)
- [Virtual queue playback](../concepts/virtual-queue-playback.md)
- [claude-dj CLI](claude-dj-cli.md)

[^1]: claude_dj/daemon/server.py
