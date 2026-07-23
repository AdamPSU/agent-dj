# Claude DJ

Spotify now-playing statusline for Claude Code and OpenCode.

## Commands

- `dj auth` — Client ID, Spotify login; multi-select agents to enable
- `dj on` / `dj off` — multi-select agents to enable/disable
- `dj tick` — hidden hook (Claude Code ~1s; OpenCode companion shells the same); polls Spotify ≤ every 5s and interpolates while playing

## Layout

Shared: `src/backend/` (`spotify`, `tracker`, `cli`, `auth_wizard`, `agents`).  
Claude: `src/backend/claude/` (`statusline`).  
OpenCode: `src/backend/opencode/` (`statusline`, bundled TUI `plugin/`).

OpenCode enable installs [kalcohol/opencode-statusline](https://github.com/kalcohol/opencode-statusline) (required) plus our companion plugin under `~/.config/opencode/plugins/`, merged into `tui.json`.
