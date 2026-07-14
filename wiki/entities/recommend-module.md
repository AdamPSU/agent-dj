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
- `next_block_seed` — 0.5/0.5 L2 blend
- `apply_cooldown` — caller-owned map
- Softmax sample over −distance / τ (default 0.15)

## Rules

≥50 indexed; n ∈ {3,4,5}; 3h cooldown; cold seed random indexed track.

Called by [orchestrator](orchestrator.md), not by CLI directly.

[^1]: backend/music/recommend.py

