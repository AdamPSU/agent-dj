# Claude DJ

Spotify now-playing statusline for [Claude Code](https://claude.ai/code).

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/AdamPSU/claude-dj-plugin/main/install.sh | bash
dj auth
```

Install puts **`dj`** on your PATH (installs [`uv`](https://docs.astral.sh/uv/) if needed). Then run **`dj auth`** in your terminal.

### Spotify app (once)

1. Create an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Add a loopback redirect (`http://127.0.0.1/callback` — login uses an ephemeral local port).
3. Paste the **Client ID** when auth asks (saved to `~/.claude-dj/config.json`).

## Use

```sh
dj auth     # Client ID + Spotify login + enable statusline
dj on       # enable statusline
dj off      # disable statusline (restores previous Claude Code bar)
dj help
```

`dj auth` turns the statusline **on** automatically. Use `dj off` / `dj on` to toggle later.

In Claude Code shell mode:

```text
!dj on
!dj off
```

### Statusline

While enabled, Claude Code runs `dj tick` about once per second. Spotify is polled at most every **5 seconds**; progress is interpolated while playing and frozen while paused:

```text
♪ Four Tet — Baby · 1:42/3:10
```

## Local storage

Under `~/.claude-dj/`:

| Path | Purpose |
|------|---------|
| `config.json` | Spotify client ID (mode 600) |
| `spotify_tokens.json` | OAuth tokens (mode 600) |
| `now_playing.json` | Short-lived now-playing cache |
| `statusline.json` | Statusline install marker |

Env `SPOTIFY_CLIENT_ID` overrides the config file if set.

## Package layout

```text
src/backend/
  cli.py           # dj entry
  config.py
  spotify.py       # auth + now playing
  tracker.py       # format + 5s poll/interpolate
  claude/          # Claude Code integration only
    statusline.py
    auth.py
```

Future agent integrations (e.g. OpenCode) go under `src/backend/<agent>/`.

## Development

```sh
git clone https://github.com/AdamPSU/claude-dj-plugin
cd claude-dj-plugin
uv sync
uv run pytest
uv run dj auth
```
