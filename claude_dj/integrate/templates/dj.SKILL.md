---
name: dj
description: Control Claude DJ (local Spotify coding companion). Use for jam, kill, statusline, sync, device, setup, help.
disable-model-invocation: true
---

Run the installed CLI `dj`.

- No args → `dj help`
- Else → `dj $ARGUMENTS`

Commands: `jam` (start recommender + enable statusline), `kill` (stop daemon), `statusline toggle` (toggle bar on/off), `sync`, `device`, `setup`, `help`.

Return the command output concisely. Do not add extra explanation unless the command fails.
