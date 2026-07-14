---
title: MuQ embeddings
description: "`backend/music/embeddings.py` \u2014 MuQ-MuLan 512-d fingerprints from\
  \ Deezer previews."
date: '2026-07-14'
tags:
- muq
- embeddings
---

`backend/music/embeddings.py` — MuQ-MuLan 512-d fingerprints from Deezer previews.

Model `OpenMuQ/MuQ-MuLan-large`, 24 kHz mono, device CUDA→MPS→CPU, loaded once per process. Used by catalog sync, not by live recommend path after indexing.[^1]

[^1]: backend/music/embeddings.py; README.md

