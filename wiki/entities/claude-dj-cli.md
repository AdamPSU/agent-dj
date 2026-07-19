---
title: dj CLI
description: Entry point `claude_dj.cli:main` (`pyproject.toml` script `dj`).
date: '2026-07-18'
tags:
- cli
- commands
- install
---

Entry point `claude_dj.cli:main` (`pyproject.toml` script `dj`).

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/AdamPSU/claude-dj-plugin/algorithm-v1/install.sh | bash
dj setup
```

## Commands

| Command | Behavior |
|---------|----------|
| `setup` | TTY wizard: client ID → login → device → statusline → `/dj` skill → MuQ |
| `jam` | statusline ensure → `ensure_session` → `ensure_daemon` → `POST /jam` |
| `kill` | `POST /kill` (stop daemon; Spotify keeps playing) |
| `statusline` | toggle Claude Code bar on/off |
| `statusline --render` | Claude Code hook (render only; not user-facing) |
| `sync` | `POST /sync` |
| `device` | auth + daemon → `GET /devices` |
| `device <id>` | auth + daemon → `POST /devices/{id}` |
| `help` | list commands |

Hidden: `__daemon__` runs FastAPI via `claude_dj.daemon.server`.

Client ID: env `SPOTIFY_CLIENT_ID` **or** `~/.claude-dj/config.json` via `resolve_spotify_client_id()`.

## Daemon spawn

If status unreachable: `Popen` same interpreter `-m claude_dj.cli __daemon__`, wait up to ~10s, log stdout/stderr to `~/.claude-dj/daemon.log`. Early process death prints log tail.[^1]

## Related

- [Control plane](../concepts/control-plane.md)
- [Daemon](daemon.md)
- [Local storage](../concepts/local-storage.md)

[^1]: claude_dj/cli.py; install.sh; claude_dj/integrate/setup.py
