# Agent DJ

Spotify now-playing statusline for Claude Code and OpenCode.

## Commands

- `dj auth` — Client ID, Spotify login; multi-select agents to enable
- `dj on` / `dj off` — multi-select agents to enable/disable
- `dj tick` — hidden hook (Claude Code ~0.5s; OpenCode companion shells `tick --json`); polls Spotify ≤ every 5s and interpolates while playing

## Layout

Shared: `src/backend/` (`spotify`, `tracker`, `cli`, `auth_wizard`, `agents`).  
Claude: `src/backend/claude/` (`statusline`).  
OpenCode: `src/backend/opencode/` (`statusline`, bundled TUI `plugin/`).

OpenCode enable installs the companion plugin under `~/.config/opencode/plugins/agent-dj` and merges it into `tui.json`. State lives in `~/.agent-dj/`.
