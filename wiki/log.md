---
title: Log
description: Chronological record of llmwiki migration, ingests, queries, and maintenance passes.
date: 2026-07-08
tags: [log, migration, maintenance]
---

Chronological record of ingests, queries, and maintenance passes.

## [2026-07-08] migration | Curated llmwiki migration kickoff

- Initialized the repo-local llmwiki scaffold in `claude-dj-plugin`.
- Indexed 50 repository sources into the local llmwiki source layer.
- Chose a true merge: `wiki/` becomes the only canonical knowledge base, while code, tests, package metadata, and `README.md` remain evidence for implementation facts.
- Replaced the placeholder overview with a migration hub, key findings table, knowledge-flow diagram, and migration queue.
- Key takeaway: migrate by topic and cite current implementation files when legacy context conflicts with code.

## [2026-07-08] migration | Merge legacy notes into wiki

- Merged product identity and command-surface knowledge into [Claude DJ](entities/claude-dj.md).
- Merged daemon and session-control knowledge into [Local Daemon Architecture](concepts/local-daemon-architecture.md) and [Session Control](concepts/session-control.md).
- Merged playback, recommendation, Spotify adapter, narration, provider research, and roadmap notes into focused wiki pages.
- Updated [Overview](overview.md) so `wiki/` is the only canonical knowledge base.
- Key takeaway: future ideas and corrections should update the nearest existing wiki page directly instead of recreating a parallel note tree.