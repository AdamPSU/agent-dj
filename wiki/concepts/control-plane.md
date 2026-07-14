---
title: Control plane
description: CLI client + localhost HTTP daemon.
date: '2026-07-14'
tags:
- architecture
- cli
- http
---

CLI client + localhost HTTP daemon.

## Commands → HTTP

| CLI | HTTP |
|-----|------|
| play | POST `/play` (+ auth + spawn) |
| status | GET `/status` |
| sync | POST `/sync` |
| device | GET `/devices` |
| device id | POST `/devices/{id}` |
| quit | POST `/quit` |

```mermaid
sequenceDiagram
  participant U as User
  participant C as CLI
  participant D as Daemon
  U->>C: play
  C->>C: ensure_session
  C->>C: ensure_daemon
  C->>D: POST /play
  D-->>C: JSON block or not_ready
```

Host/port from `backend/config.py`.[^1]

[^1]: backend/cli.py; backend/daemon.py; backend/config.py

