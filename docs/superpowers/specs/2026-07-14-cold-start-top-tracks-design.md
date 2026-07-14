# Cold-start seed from Spotify top tracks

**Date:** 2026-07-14  
**Branch:** `algorithm-v1`  
**Status:** approved for implementation planning  

## Problem

Cold start today picks a **uniform random** indexed embedding (`recommend_block` when `seed_embed is None`). That ignores what the user actually listens to. Playlist membership alone is a weak proxy for recent affinity.

## Goal

Replace the random cold seed with a **history-informed sample** that reuses the same stochastic style as in-block k-NN selection (softmax over weighted candidates), not a deterministic “always #1” or centroid collapse.

## Non-goals

- Stronger cooldown / anti-repeat from full listening history  
- Mid-session taste bias after the first block  
- `recently-played` (only ~50 plays; different signal)  
- Top artists / genres / Spotify Recommendations API  
- Changing `next_block_seed` (0.5 last + 0.5 session_start)  
- Changing in-block neighbor softmax  

## Constraints (Spotify API)

| Fact | Implication |
|------|-------------|
| `GET /me/top/{type}` | Affinity lists, not raw play logs |
| `time_range` ∈ {`short_term`, `medium_term`, `long_term`} | ~4 weeks / ~6 months / ~1 year only — no custom windows |
| `limit` max 50 | Fetch 50 for catalog intersection coverage |
| Scope | Requires `user-top-read` (users re-auth once) |
| Audio Features / Recommendations | Deprecated / unavailable for new apps — irrelevant here |

Only tracks that exist in the **local indexed catalog** can contribute embeddings. Top tracks outside owned playlists (or not yet embedded) are skipped.

## Design

### High-level flow

```
play (cold: no seed_embed)
  → pick time_range ~ Uniform{short, medium, long}
  → GET /me/top/tracks?time_range=…&limit=50
  → keep rows whose spotify_id is indexed locally
  → rank r=0..k-1 → pseudo-distance d = r / max(k-1, 1)
  → softmax_sample(candidates, tau=DEFAULT_TAU)  # same as in-block
  → seed_embed = embedding(pick)
  → recommend_block(..., seed_embed=seed_embed) as today
```

If the eligible pool is empty **or** the top-tracks fetch fails → **silent fallback** to today’s random indexed seed so `/play` still works.

### When this runs

| Situation | Seed source |
|-----------|-------------|
| Fresh cold `play` (`seed_embed is None`) | Top-tracks softmax (this design) |
| Next block while attached | `next_block_seed(last, session_start)` unchanged |
| Re-attach after **yield** with session embeds | Blended next-block seed unchanged |
| Top fetch fail / no indexed intersection | Random indexed seed (current behavior) |

Idempotent `/play` while already `attached` does not re-seed.

### Rank → distance

For eligible candidates ordered by Spotify top rank (position in the API list, after filtering):

- `r = 0` for the highest-ranked eligible track  
- `d(r) = r / max(k - 1, 1)` so #1 has distance `0`, last has distance `1`  
- If `k == 1`, single candidate, distance `0`  

This maps cleanly into existing `softmax_sample`, which uses `P ∝ exp(−distance / τ)`.

### Temperature

Reuse `DEFAULT_TAU = 0.15` so cold-start “sharpness” matches in-block neighbor sampling. No separate knob in v1.

### Time range

Each cold start draws:

```text
time_range ~ Uniform{ short_term, medium_term, long_term }
```

Rationale: user wants variety across affinity horizons; Spotify does not expose finer windows. Uniform is simple and avoids over-fitting to “this month only.”

### Limit

`limit=50` (API maximum). Softmax still prefers top ranks at τ=0.15; the long tail mainly improves odds that **something** in the list is indexed.

## Module boundaries

| Piece | Responsibility |
|-------|----------------|
| `backend/config.py` | Add `user-top-read` to `SPOTIFY_SCOPES` |
| `backend/adapters/spotify.py` | `iter_top_tracks(time_range, limit=50)` (or equivalent list helper) |
| `backend/music/recommend.py` | Pure `sample_cold_seed_from_top(conn, top_rows, *, tau, rng) -> list[float] | None` |
| Orchestrator / daemon call site | On cold mint: choose range, fetch tops, call pure helper, pass `seed_embed` into `_mint_and_start` / `recommend_block` |

**Purity rule:** `recommend_block` and `sample_cold_seed_from_top` do not call Spotify. HTTP stays in adapter + orchestration so unit tests inject fake `top_rows`.

### `top_rows` shape (minimal)

Ordered list (API order = rank):

```python
{"spotify_id": str, ...}  # only spotify_id required for matching
```

Helper:

1. Walk in order; resolve each id to local indexed track + embedding  
2. Build candidates `{distance, track_id, spotify_id, ...}`  
3. If empty → `None`  
4. Else `softmax_sample` → `get_embedding` → return vector  

Optional metadata for status/debug (v1 nice-to-have, not required for play):

- `cold_seed_time_range`  
- `cold_seed_spotify_id`  
- `cold_seed_source`: `top_tracks` | `random_fallback`  

## Auth / migration

- New scope string requires users with existing tokens to **re-login** (`ensure_session` already clears invalid tokens and re-runs PKCE login when `/me` fails; after scope change, Spotify may reject until re-consent — `play` path already opens login when session invalid).  
- Document in README: export still needs `SPOTIFY_CLIENT_ID`; first play after upgrade may re-open browser.

## Failure modes

| Failure | Behavior |
|---------|----------|
| Missing `user-top-read` / 403 | Fallback random seed |
| Network / 5xx | Fallback random seed |
| Zero intersection with indexed catalog | Fallback random seed |
| Catalog `indexed < 50` | Existing `not_ready` (unchanged; cold seed never reached usefully) |

No user-facing hard error for top-track failures in v1.

## Testing

- **Unit (`recommend`):** rank distances; single eligible; empty pool → `None`; softmax prefers lower rank in aggregate (seeded RNG); τ edge cases  
- **Unit (`spotify` adapter):** request path/params for `time_range` + `limit` (mock HTTP)  
- **Orchestrator:** cold play with injectable top fetcher → seed used; fetcher error → still mints with random path; non-cold paths never call fetcher  
- **Config:** scopes include `user-top-read`  

## Success criteria

1. Cold `/play` with indexed top-track overlap uses a softmax-sampled top embedding as seed more often than pure random over the full catalog.  
2. Time range varies across cold plays (uniform over three API values).  
3. In-block algorithm and next-block blend unchanged.  
4. Offline / no-top-data environments still play via random fallback.  
5. Tests cover pure helper without live Spotify.

## Open questions (deferred)

- Persist last cold-seed range in status for the statusline  
- Weight time ranges (e.g. prefer short_term)  
- Cache top lists on a TTL to reduce API calls  

## Related code

- `backend/music/recommend.py` — `recommend_block`, `softmax_sample`, `DEFAULT_TAU`  
- `backend/orchestrator.py` — `play` / `_mint_and_start` seed plumbing  
- `backend/adapters/spotify.py` — auth + API helpers  
- `backend/config.py` — `SPOTIFY_SCOPES`  
- `docs/superpowers/specs/2026-07-14-playback-virtual-queue-design.md` — session modes  
