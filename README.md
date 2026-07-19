# Claude DJ

Local Spotify DJ companion for coding sessions (Claude Code statusline + shell/`!` command mode).

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/AdamPSU/claude-dj-plugin/algorithm-v1/install.sh | bash
dj setup
```

Install puts **`dj`** on your PATH (installs [`uv`](https://docs.astral.sh/uv/) if needed). Then run **`dj setup`** in your terminal (interactive: Spotify + MuQ).

### Spotify app (once)

1. Create an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Add a loopback redirect (`http://127.0.0.1/callback` style — login uses an ephemeral local port).
3. Paste the **Client ID** when setup asks (saved to `~/.claude-dj/config.json`). No shell `export` required.

Optional flags (still interactive — confirms Spotify + MuQ):

```sh
dj setup --client-id <id> --device-id <connect-id>
```

## Use

```sh
dj play              # auth if needed, start daemon, mint + play
dj status
dj sync
dj device            # list Connect devices
dj device <id>       # prefer a device
dj quit
dj setup             # re-run wizard (idempotent)
```

In **Claude Code**, prefer shell/command mode for zero model lag:

```text
!dj play
!dj status
```

(Optional skill still installs as `/dj` → same CLI.)

### Statusline

Setup (and first `play`) wraps your existing Claude Code `statusLine`. When DJ is attached and/or catalog sync has work:

```text
♪ Four Tet — Baby · 1:42/3:10 · sync: 128/900 songs
```

## How it works

```text
dj …  →  localhost HTTP  →  daemon (FastAPI)
```

On play/sync the daemon pulls **owned** Spotify playlists, then embeds pending tracks (Deezer preview → MuQ → sqlite-vec). Playback is a **virtual queue** on Spotify Connect (multi-URI blocks + 1s monitor).

## Local storage

Under `~/.claude-dj/`:

| Path | Purpose |
|------|---------|
| `config.json` | Spotify client ID (mode 600) |
| `spotify_tokens.json` | OAuth tokens (mode 600) |
| `device.json` | Preferred Connect device |
| `catalog.db` | Playlists, tracks, embeddings |
| `statusline.json` | Statusline install marker |
| `daemon.log` | Background daemon log |

Env `SPOTIFY_CLIENT_ID` still overrides the config file if set.

## Local embeddings (MuQ-MuLan)

- **Disk:** ~2.7 GB model download on first use (Hugging Face)
- **RAM:** ~4–8 GB free recommended
- **Device:** CUDA → MPS → CPU

## Package layout

```text
claude_dj/
  cli.py              # argparse entry (PATH: dj)
  config.py           # paths + client id
  daemon/             # FastAPI control plane
  session/            # plan + Session mint/reconcile
  catalog/            # sqlite + sync
  recommend/          # Focus/Taste blocks
  playback/           # PlaybackPort + Spotify/Fake
  embeddings/         # MuQ-MuLan
  adapters/           # spotify, deezer
  integrate/          # setup wizard, statusline, /dj skill
```

## Development

```sh
git clone https://github.com/AdamPSU/claude-dj-plugin
cd claude-dj-plugin
uv sync
uv run pytest
uv run dj setup --client-id <id>
```
