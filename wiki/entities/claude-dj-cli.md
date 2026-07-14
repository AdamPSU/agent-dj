---
title: claude-dj CLI
description: Entry point `backend.cli:main` (`pyproject.toml` script `claude-dj`).
date: '2026-07-14'
tags:
- cli
- commands
---

Entry point `backend.cli:main` (`pyproject.toml` script `claude-dj`).

## Commands

| Command | Behavior |
|---------|----------|
| `play` | `ensure_session` → `ensure_daemon` → `POST /play` |
| `status` | `GET /status` |
| `sync` | `POST /sync` |
| `device` | auth + daemon → `GET /devices` |
| `device <id>` | auth + daemon → `POST /devices/{id}` |
| `quit` | `POST /quit` |

Hidden: `__daemon__` runs FastAPI.

## Daemon spawn

If status unreachable: `Popen` same interpreter `-m backend.cli __daemon__`, wait up to ~10s, log stdout/stderr to `~/.claude-dj/daemon.log`. Early process death prints log tail.[^1]

## Related

- [Control plane](../concepts/control-plane.md)
- [Daemon](daemon.md)

[^1]: backend/cli.py

