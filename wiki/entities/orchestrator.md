---
title: Orchestrator
description: '`backend/orchestrator.py` owns the DJ **session**: mint blocks, virtual
  queue, cooldown map, mode, and `tick()` reconcile.'
date: '2026-07-14'
tags:
- orchestrator
- session
- dj
---

`backend/orchestrator.py` owns the DJ **session**: mint blocks, virtual queue, cooldown map, mode, and `tick()` reconcile.

## Responsibilities

- `play(conn)`: start/re-attach; idempotent while attached; after yield mints with blended seed when possible
- `advance(conn)`: next planned track or mint new block (tests + future; monitor uses tick)
- `tick(conn)`: poll playback port; advance / skip / yield
- `status_snapshot(conn)`: mode, block, virtual_queue, now_playing, indexed readiness

## Not responsible

- HTTP (daemon)
- Catalog sync
- Embedding generation
- ElevenLabs

## Related

- [Virtual queue playback](../concepts/virtual-queue-playback.md)
- [Recommend module](recommend-module.md)
- [Daemon](daemon.md)

[^1]: backend/orchestrator.py

