---
title: Recommend module
description: "`backend/music/recommend.py` \u2014 pure block selection over sqlite-vec\
  \ (no HTTP, no Spotify writes)."
date: '2026-07-14'
tags:
- recommend
- algorithm
---

`backend/music/recommend.py` — pure block selection over sqlite-vec (no HTTP, no Spotify writes).

## API

- `recommend_block(conn, n=5, …)` — full block or typed error
- `next_block_seed(last, recency=None)` — L2(0.7 last + 0.3 recency) or last only
- `sample_seed_from_top(conn, top_rows, …)` — rank-softmax over indexed tops
- `apply_cooldown` — caller-owned map
- Softmax sample over −distance / τ (default 0.15)

## Rules

≥50 indexed; n ∈ {3,4,5}; 3h cooldown; cold seed via tops (orchestrator) or random fallback.

Called by [orchestrator](orchestrator.md), not by CLI directly.

[^1]: backend/music/recommend.py

