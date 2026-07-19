---
title: MuQ embeddings
description: "`claude_dj/embeddings/muq.py` \u2014 MuQ-MuLan 512-d fingerprints from\
  \ Deezer previews."
date: '2026-07-18'
tags:
- muq
- embeddings
---

`claude_dj/embeddings/muq.py` — MuQ-MuLan 512-d fingerprints from Deezer previews.

Model `OpenMuQ/MuQ-MuLan-large`, 24 kHz mono, device CUDA→MPS→CPU, loaded once per process. Used by catalog sync; live recommend reads stored vectors only.[^1]

[^1]: claude_dj/embeddings/muq.py; README.md
