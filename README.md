# Claude DJ

Local OpenCode companion for Spotify during coding sessions.

## Control plane

```text
/dj …  →  claude-dj CLI  →  localhost HTTP  →  daemon (FastAPI)
```

## Spotify setup

1. Create an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Allow loopback redirects (`http://127.0.0.1/callback` style). Login uses an ephemeral local port.
3. Export the client ID:
   ```sh
   export SPOTIFY_CLIENT_ID=<your-client-id>
   ```
4. Log in:
   ```sh
   uv run claude-dj spotify-login
   ```
   Tokens: `~/.claude-dj/spotify_tokens.json` (mode `600`).

`claude-dj start` runs login automatically if that token file is missing.

## Commands

```sh
uv run claude-dj spotify-login
uv run claude-dj start
uv run claude-dj status
uv run claude-dj sync      # stub
uv run claude-dj quit
```

## Local embeddings (MuQ-MuLan)

Track fingerprints use **MuQ-MuLan** (512-d), loaded once in the daemon process.

- **Disk:** ~2.7 GB model download on first use (Hugging Face)
- **RAM:** plan on ~4–8 GB free for comfortable single-stream inference (estimate)
- **Device:** CUDA → MPS → CPU automatically
- **Input:** Deezer preview URL or raw audio bytes streamed in memory (24 kHz mono)

## Development

```sh
uv sync
uv run pytest
```

