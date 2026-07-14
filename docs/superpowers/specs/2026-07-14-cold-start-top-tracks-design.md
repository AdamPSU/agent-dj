# Cold-start seed + recency-aware next-block blend

**Date:** 2026-07-14  
**Branch:** `algorithm-v1`  
**Status:** implemented on `algorithm-v1`

## Problem

1. **Cold start** picks a **uniform random** indexed embedding (`recommend_block` when `seed_embed is None`). That ignores what the user actually listens to.
2. **Next-block seed** is `L2(0.5·last + 0.5·session_start)` only — continuity without a pull toward recent affinity. **Target:** drop session_start from the blend; use last + recency only.

Playlist membership alone is a weak proxy for taste.

## Goal

1. Replace random cold seed with a **history-informed sample** (softmax over ranked top tracks), same stochastic style as in-block k-NN — not centroid collapse or always-#1.
2. Change next-block blend to **last + recency only** (no session_start in the linear combo). Recency from **short_term** top tracks (sampled the same way).

## Non-goals

- Stronger cooldown / anti-repeat from full listening history  
- Mid-session taste bias beyond the 0.3 recency term  
- `recently-played` (only ~50 plays; different signal)  
- Top artists / genres / Spotify Recommendations API  
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

### A. Cold-start seed

```
play (cold: no seed_embed)
  → pick time_range ~ Uniform{short, medium, long}
  → GET /me/top/tracks?time_range=…&limit=50
  → keep rows whose spotify_id is indexed locally
  → rank r=0..k-1 → pseudo-distance d = r / max(k-1, 1)
  → softmax_sample(candidates, tau=DEFAULT_TAU)
  → seed_embed = embedding(pick)
  → recommend_block(..., seed_embed=seed_embed)
```

If the eligible pool is empty **or** the top-tracks fetch fails → **silent fallback** to today’s random indexed seed so `/play` still works.

### B. Next-block seed (updated)

```text
next = L2(0.7·last + 0.3·recency)
```

These are **embedding vectors**, not “% of the block.” The blend is the **seed point** for the next block’s first k-NN walk:

| Component | Weight | Meaning |
|-----------|--------|---------|
| `last` | 0.7 | Embedding of the **last track** of the previous block (local continuity) |
| `recency` | 0.3 | Fresh sample from **short_term** tops only (“songs like me lately”) |

**No `session_start` in the next-block blend.** Session open still exists as the cold-start seed for block 1 only; it does not keep pulling later blocks back to the opening vibe.

**Reading:** next seed ≈ **70% where we just were, 30% recent taste.**

**Recency sampling (every next-block mint):**

1. `GET /me/top/tracks?time_range=short_term&limit=50`  
2. Same rank → distance → `softmax_sample` → embedding as cold helper  
3. If pool empty / fetch fails → **use `last` alone** (L2-normalize if needed). No session_start fallback.

`next_block_seed` signature becomes:

```python
def next_block_seed(
    last_embed: Sequence[float],
    recency_embed: Sequence[float] | None = None,
) -> list[float]:
```

- If `recency_embed` is `None` → return `last` (or L2 copy of last)  
- If present → `L2(0.7·last + 0.3·recency)`  
- Degenerate norm → prefer `last`

### When each path runs

| Situation | Seed source |
|-----------|-------------|
| Fresh cold `play` (`seed_embed is None`) | Uniform random time_range + rank-softmax tops → `seed_embed` |
| Next block while attached | `next_block_seed(last, recency)` with **short_term** sample |
| Re-attach after **yield** with last embed | Same last + short_term recency blend |
| Top fetch fail / no indexed intersection (cold) | Random indexed seed |
| Top fetch fail (recency only) | `last` only |

Idempotent `/play` while already `attached` does not re-seed.

### Rank → distance

For eligible candidates ordered by Spotify top rank (API order, after filtering to indexed):

- `r = 0` for the highest-ranked eligible track  
- `d(r) = r / max(k - 1, 1)` so #1 has distance `0`, last has distance `1`  
- If `k == 1`, single candidate, distance `0`  

Used by both cold start and short_term recency sampling via shared pure helper.

### Temperature

Reuse `DEFAULT_TAU = 0.15` for all top-track softmax samples. No separate knob in v1.

### Time range policy

| Use | Policy |
|-----|--------|
| Cold start | `Uniform{ short_term, medium_term, long_term }` |
| Recency leg (next block / yield re-attach) | **Always `short_term`** |

Rationale: cold open explores affinity horizon; ongoing blocks pull gently toward “what I’ve been into lately” (~4 weeks).

### Limit

`limit=50` (API maximum) for both cold and recency fetches.

## Module boundaries

| Piece | Responsibility |
|-------|----------------|
| `backend/config.py` | Add `user-top-read` to `SPOTIFY_SCOPES` |
| `backend/adapters/spotify.py` | `iter_top_tracks(time_range, limit=50)` |
| `backend/music/recommend.py` | Pure `sample_seed_from_top(...)`; `next_block_seed(last, recency=None)` → `0.7/0.3` or last-only |
| Orchestrator | Cold mint: random range + fetch + sample → `seed_embed`. Next mint / yield re-attach: fetch **short_term**, sample recency, call `next_block_seed(last, recency)`. May drop storing `session_start_embed` for blending (still fine to keep for debug/status if useful). |

**Purity rule:** recommend helpers do not call Spotify. HTTP stays in adapter + orchestration; tests inject `top_rows` / `recency_embed`.

### `top_rows` shape (minimal)

Ordered list (API order = rank):

```python
{"spotify_id": str, ...}  # only spotify_id required for matching
```

Shared helper:

1. Walk in order; resolve each id to local indexed track + embedding  
2. Build candidates `{distance, track_id, spotify_id, ...}`  
3. If empty → `None`  
4. Else `softmax_sample` → `get_embedding` → return vector  

Optional metadata for status/debug (v1 nice-to-have):

- `cold_seed_time_range`  
- `cold_seed_spotify_id` / `recency_spotify_id`  
- `cold_seed_source`: `top_tracks` | `random_fallback`  
- `next_seed_had_recency`: bool  

## Auth / migration

- New scope requires users with existing tokens to **re-login** once.  
- Document in README: first play after upgrade may re-open browser.

## Failure modes

| Failure | Behavior |
|---------|----------|
| Missing `user-top-read` / 403 (cold) | Random catalog seed |
| Network / 5xx (cold) | Random catalog seed |
| Zero intersection (cold) | Random catalog seed |
| Recency fetch fail / empty | `next_block_seed` with last only |
| Catalog `indexed < 50` | Existing `not_ready` |

No user-facing hard error for top-track failures in v1.

## Testing

- **Unit (`recommend`):** rank distances; empty pool → `None`; `next_block_seed` 0.7/0.3 + L2; last-only when recency `None`; degenerate norm  
- **Unit (`spotify`):** path/params for `time_range` + `limit`  
- **Orchestrator:** cold play uses tops; next mint requests **short_term** only for recency; fetcher error cold → random path; fetcher error next → still mints with last-only seed  
- **Config:** scopes include `user-top-read`  
- **Regression:** existing next-block tests updated for new weights (no session_start term)  

## Success criteria

1. Cold `/play` with indexed top overlap uses softmax-sampled top embedding as seed (not pure catalog random) when fetch works.  
2. Cold time_range varies uniformly across the three API values.  
3. Next-block seed is `L2(0.7 last + 0.3 recency)` when short_term sample succeeds; **no session_start term**.  
4. Recency always uses `short_term`, never medium/long.  
5. Offline / no-top-data still plays (random cold; last-only next).  
6. In-block neighbor algorithm unchanged.  
7. Pure helpers testable without live Spotify.

## Open questions (deferred)

- Cache short_term tops on a short TTL to avoid fetch-every-block  
- Expose seed metadata on `/status` for statusline  
- Weight cold time ranges non-uniformly  

## Related code

- `backend/music/recommend.py` — `recommend_block`, `softmax_sample`, `next_block_seed`, `DEFAULT_TAU`  
- `backend/orchestrator.py` — `play` / `_mint_and_start` / next-block mint  
- `backend/adapters/spotify.py` — auth + API helpers  
- `backend/config.py` — `SPOTIFY_SCOPES`  
- `docs/superpowers/specs/2026-07-14-playback-virtual-queue-design.md` — session modes  
