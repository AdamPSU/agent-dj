---
title: claude-dj CLI
description: Entry point `claude_dj.cli:main` (`pyproject.toml` script `claude-dj`).
date: '2026-07-18'
tags:
- cli
- commands
- install
---

Entry point `claude_dj.cli:main` (`pyproject.toml` script `claude-dj`).

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/AdamPSU/claude-dj-plugin/main/install.sh | bash
```

`install.sh` ensures `uv`, runs `uv tool install`, then `claude-dj setup`.

## Commands

| Command | Behavior |
|---------|----------|
| `setup` | TTY wizard (questionary): client ID → login → device → statusline → `/dj` skill |
| `play` | statusline ensure → `ensure_session` → `ensure_daemon` → `POST /play` |
| `status` | `GET /status` |
| `sync` | `POST /sync` |
| `device` | auth + daemon → `GET /devices` |
| `device <id>` | auth + daemon → `POST /devices/{id}` |
| `quit` | `POST /quit` |
| `statusline` | render DJ statusline row (Claude Code) |

Hidden: `__daemon__` runs FastAPI via `claude_dj.daemon.server`.

Client ID: env `SPOTIFY_CLIENT_ID` **or** `~/.claude-dj/config.json` via `resolve_spotify_client_id()`.

## Daemon spawn

If status unreachable: `Popen` same interpreter `-m claude_dj.cli __daemon__`, wait up to ~10s, log stdout/stderr to `~/.claude-dj/daemon.log`. Early process death prints log tail.[^1]

## Related

- [Control plane](../concepts/control-plane.md)
- [Daemon](daemon.md)
- [Local storage](../concepts/local-storage.md)

[^1]: claude_dj/cli.py; install.sh; claude_dj/integrate/setup.py
