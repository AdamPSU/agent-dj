# Claude DJ

Spotify now-playing statusline for Claude Code.

## Commands

- `dj auth` — Client ID, Spotify login; **enables statusline automatically**
- `dj on` / `dj off` — toggle Claude Code statusline
- `dj tick` — hidden hook (Claude Code runs this ~1s); polls Spotify ≤ every 5s and interpolates progress while playing

## Layout

Shared code: `src/backend/` (`spotify`, `tracker`, `cli`).  
Claude-only: `src/backend/claude/` (`statusline`, `auth`).  
Future agents: `src/backend/<agent>/`.
