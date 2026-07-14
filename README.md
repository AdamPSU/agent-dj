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
4. Run `play` (opens browser login if needed, starts daemon + catalog sync):
   ```sh
   uv run claude-dj play
   ```
   Tokens: `~/.claude-dj/spotify_tokens.json` (mode `600`).

`claude-dj play` checks that the saved session still works (refresh if needed). If the token file is missing, expired beyond refresh, or refresh fails, it opens browser login again. After upgrades that add OAuth scopes (e.g. `user-top-read` for cold-start seeding), re-run `play` so the browser consent screen can grant them.

## Commands

```sh
uv run claude-dj play              # auth if needed, start daemon, kick sync, mint + play block
uv run claude-dj status            # debug: mode, queue, counts, now playing
uv run claude-dj sync              # re-run catalog pull + embed pending/retry
uv run claude-dj device            # list Spotify Connect devices + preferred id
uv run claude-dj device <id>       # prefer a device (saved under ~/.claude-dj/)
uv run claude-dj quit
```

On play/sync the daemon pulls **owned** Spotify playlists, then for each `pending`/`retry` track: Deezer preview → MuQ embed → store (one at a time).

When the catalog has ≥50 indexed tracks, `play` mints a recommendation block onto a **virtual queue** and loads the **whole block** on Spotify Connect (`PUT /me/player/play` with all block URIs) so client skip works within the plan. Cold start seeds from Spotify **top tracks** (rank-softmax; time range random among short/medium/long); the next block seed is `L2(0.7·last + 0.3·short_term recency)`. A background monitor polls the player (~3–5s): reconciles skips/advances within the plan, **yields** if you play something outside the plan, and mints the next block near the end of the last planned track. Repeat `play` while attached is idempotent; after yield, `play` re-attaches with a new block.

`/status` includes `mode` (`idle`|`attached`|`yielded`), `now_playing`, `virtual_queue`, `current_block`, `indexed`, `recommend_ready`.

## Local storage

SQLite catalog at `~/.claude-dj/catalog.db` with **sqlite-vec** (512-d nearest neighbor).

Tables: `playlists`, `tracks`, `playlist_tracks`, `track_embeddings`.  
Track status: `pending` | `indexed` | `skipped` | `retry`.

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

