---
title: Daemon
description: Long-lived FastAPI + uvicorn on `127.0.0.1:8787`.
date: '2026-07-14'
tags:
- daemon
- fastapi
---

Long-lived FastAPI + uvicorn on `127.0.0.1:8787`.

## Routes

| Method | Path | Role |
|--------|------|------|
| GET | `/status` | Sync + orchestrator snapshot |
| POST | `/play` | Kick sync, ensure monitor, `orchestrator.play` |
| POST | `/sync` | Kick catalog sync |
| GET | `/devices` | List Connect devices + preferred id |
| POST | `/devices/{id}` | Save preferred device + transfer |
| POST | `/quit` | Stop monitor + uvicorn |

## Background

- Catalog sync thread (`sync.kick`)
- DJ monitor thread (~3–5s) while mode `attached`
- Playback: `SpotifyPlayback` if tokens exist else `FakePlayback`

## Related

- [Orchestrator](orchestrator.md)
- [Virtual queue playback](../concepts/virtual-queue-playback.md)

[^1]: backend/daemon.py

