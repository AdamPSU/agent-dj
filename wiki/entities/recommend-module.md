---
title: Recommend module
description: "`claude_dj/recommend/engine.py` \u2014 pure Focus + Taste block recommender\
  \ over MuQ embeddings. No Spotify HTTP. Wired from `Session.play` / mint path."
date: '2026-07-18'
tags:
- recommend
- focus
- taste
---

`claude_dj/recommend/engine.py` — pure Focus + Taste block recommender over MuQ embeddings. No Spotify HTTP. Wired from `Session.play` / mint path.

## API

| Symbol | Role |
|--------|------|
| `resolve_session_start(conn, top_rows=…)` | F₀ + optional T from tops ∩ indexed (rank-softmax); else random catalog, T=None |
| `recommend_block(conn, focus=…, taste=…)` | Walk focus; softmax picks; empty neighborhood **ends block early** |
| `advance_focus(focus, taste=…)` | Between blocks: slide toward T + noise |
| `apply_cooldown(map, ids, now)` | Caller marks played tracks |
| `sample_seed_from_tops` | Rank-softmax among indexed tops |

Caller chooses seed mode (`short_term` / `medium_term` / `long_term` / `recently_played`) and fetches rows; recommend never calls Spotify.

## Related

- [Session](session.md)
- [Recommendation blocks](../concepts/recommendation-blocks.md)

[^1]: claude_dj/recommend/engine.py; tests/test_recommend.py
