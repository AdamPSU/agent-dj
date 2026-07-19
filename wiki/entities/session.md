---
title: Session
description: "`claude_dj/session/` \u2014 **Plan** (`plan.py`) + **Session** (`session.py`).\
  \ Owns the virtual queue, Focus/Taste, cooldown, and playback reconcile."
date: '2026-07-18'
tags:
- session
- plan
- dj
- focus
- taste
---

`claude_dj/session/` — **Plan** (`plan.py`) + **Session** (`session.py`). Owns the virtual queue, Focus/Taste, cooldown, and playback reconcile.

> Historical wiki filename: `orchestrator.md` (class used to live in `backend/orchestrator.py`).

## Session state

| Field | Role |
|-------|------|
| `plan` | Virtual queue + cursor (`Plan`) |
| `focus` / `taste` | Recommend F and optional T |
| `cooldown` | `{track_id: expiry}` after played blocks |
| `mode` | `idle` \| `attached` |
| `_block_ends` | Exclusive end indices of each minted block |

## Flows

- **`play(conn)`**: if attached + plan → resume. Else seed → `resolve_session_start` → mint **two blocks** → `start_block`. Empty → `empty_block`.
- **`tick`**: `observe` → on `advanced` move cursor; when cursor enters the **last loaded block**, mint **one** more (always keep two ahead). Pause never mints.
- **Foreign**: idle, clear plan + F/T/cooldown + `_block_ends`, `quit: true`.

## Related

- [Virtual queue playback](../concepts/virtual-queue-playback.md)
- [Recommend module](recommend-module.md)
- [Daemon](daemon.md)

[^1]: claude_dj/session/session.py; claude_dj/session/plan.py; tests/test_orchestrator.py
