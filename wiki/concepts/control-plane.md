---
title: Control plane
description: CLI client + localhost HTTP daemon. Host tooling (setup, statusline,
  skill) lives in `claude_dj/integrate/` and does not go through the daemon.
date: '2026-07-18'
tags:
- architecture
- cli
- http
---

CLI client + localhost HTTP daemon. Host tooling (setup, statusline, skill) lives in `claude_dj/integrate/` and does not go through the daemon.

## Commands → HTTP

| CLI | HTTP |
|-----|------|
| setup | local only (config, OAuth, device, Claude Code) |
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
  D-->>C: JSON
```

Host/port from `claude_dj/config.py` (`127.0.0.1:8787`).[^1]

[^1]: claude_dj/cli.py; claude_dj/daemon/server.py; claude_dj/config.py
