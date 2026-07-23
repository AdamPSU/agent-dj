# Statusline Spotify Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strip the repo to a Claude Code statusline Spotify now-playing tracker (`setup` / `on` / `off` / `tick`) with 5s polls and pause-aware interpolation — no daemon, catalog, Deezer, MuQ, or recommender.

**Architecture:** Shared backend under `src/backend/`; agent-specific integration under `src/backend/claude/` (future: `opencode/`, etc.). `dj tick` polls Spotify at most every 5s, caches to disk, interpolates progress only while playing.

**Tech stack:** Python ≥3.12, stdlib HTTP, beaupy, pytest. Package name `backend`, entry `dj = backend.cli:main`.

## Global constraints

- No fallbacks, no backward compatibility, no legacy migrations
- No FastAPI/daemon; no torch/muq/librosa/soundfile/sqlite-vec
- Spotify scope: only `user-read-playback-state`
- Setup: no CLI flags
- Drop `/dj` skill
- `POLL_S = 5.0`, `STALE_S = 30.0`
- Do not interpolate when paused; force poll when progress would pass duration
- Only Claude-specific code lives in `backend/claude/`

## Target layout

```text
src/backend/
  __init__.py
  cli.py              # shared CLI entry (dispatches; agent hooks via backend.claude)
  config.py           # APP_DIR, tokens, now_playing cache, Spotify constants
  spotify.py          # PKCE, tokens, get_now_playing
  tracker.py          # format_line, cache I/O, poll/interpolate, resolve_snapshot
  claude/
    __init__.py
    statusline.py     # Claude Code settings on/off + tick (user bar + tracker)
    setup.py          # interactive setup for Claude users
tests/
  test_config.py
  test_spotify.py
  test_tracker.py
  test_claude_statusline.py
  test_cli.py
  test_claude_setup.py
pyproject.toml
README.md
install.sh
```

**Delete:** entire `claude_dj/` tree, dead tests, obsolete specs/wiki pages for removed systems.

## Interfaces

### `backend.config`
- `APP_DIR`, `SPOTIFY_TOKEN_PATH`, `NOW_PLAYING_PATH`, `CONFIG_PATH`
- `SPOTIFY_SCOPES = "user-read-playback-state"`
- `resolve_spotify_client_id()`, `set_spotify_client_id()`, `ConfigError`

### `backend.spotify`
- `login()`, `ensure_session()`, `session_is_valid()`, `get_access_token()`
- `get_now_playing() -> dict | None`  
  keys: `spotify_id`, `name`, `artists`, `progress_ms`, `duration_ms`, `is_playing`

### `backend.tracker`
- `POLL_S = 5.0`, `STALE_S = 30.0`
- `format_ms`, `music_glyph`, `format_line(snap, *, color, now)`
- `needs_poll`, `display_progress`, `resolve_snapshot`, `load_cache`/`save_cache`/`clear_cache`

### `backend.claude.statusline`
- Claude paths: `CLAUDE_SETTINGS_PATH`, `STATUSLINE_MARKER`
- `ensure_installed`, `uninstall`, `is_installed`, `tick` (previous user command + tracker line)
- Install command: `dj tick`

### `backend.cli`
- `setup` → `backend.claude.setup.run`
- `on` / `off` / `tick` → claude statusline
- `help`; `tick` omitted from user help text

---

### Task 1: Scaffold shared backend + pyproject

- [ ] Create `src/backend/{__init__,config,spotify,tracker,cli}.py` and `src/backend/claude/{__init__,statusline,setup}.py`
- [ ] Point `pyproject.toml` at `backend` package (src layout), deps: beaupy only; script `dj = backend.cli:main`
- [ ] Tests for config scopes + paths
- [ ] Commit

### Task 2: Spotify module

- [ ] Auth + `get_now_playing` only; tests
- [ ] Commit

### Task 3: Tracker (format + poll/interpolate)

- [ ] format_line (no sync UI)
- [ ] 5s cache, pause freeze, duration force-poll, STALE_S on error
- [ ] Tests
- [ ] Commit

### Task 4: Claude statusline + setup

- [ ] on/off against `~/.claude/settings.json`
- [ ] tick = user previous bar + tracker line
- [ ] setup: client id → login → on (no flags/device/muq/skill)
- [ ] Tests
- [ ] Commit

### Task 5: CLI + delete dead tree

- [ ] Slim CLI
- [ ] Remove `claude_dj/`, old tests, dead docs
- [ ] README + install.sh
- [ ] Full `uv run pytest`
- [ ] Commit

## Spec coverage

| Requirement | Area |
|-------------|------|
| Shared vs Claude split | `backend/*` vs `backend/claude/*` |
| No daemon/Deezer/MuQ/recommend | deleted |
| on/off/tick/setup | cli + claude |
| 5s poll + pause-aware interpolate | tracker |
| Single scope | config + spotify |
