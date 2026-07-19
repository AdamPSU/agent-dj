---
name: dj
description: Control Claude DJ (local Spotify coding companion). Use for jam, kill, sync, device, setup, help.
disable-model-invocation: true
---

Run the installed CLI `dj`.

- No args → `dj help`
- Else → `dj $ARGUMENTS`

Commands: `jam` (start recommender + enable statusline), `kill` (stop daemon + disable statusline), `sync`, `device` (list only), `setup`, `help`.

Output is plain text. Return it as-is. Do not debug, re-run, or explain catalog sync when jam says songs are being synced — the daemon starts the jam once enough tracks are indexed.
