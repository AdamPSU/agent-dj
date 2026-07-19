# Log

## [2026-07-14] update | Orchestrator + playback + music package

- Updated [overview](overview.md) for E2E play path, `device`, virtual queue
- Created [virtual-queue-playback](concepts/virtual-queue-playback.md), [session](entities/session.md) (was orchestrator), [playback-module](entities/playback-module.md)
- Updated CLI, daemon, recommend, control-plane, spotify, muq paths to `backend/music/`
- Key takeaway: DJ music path wired end-to-end; ElevenLabs still future

## [2026-07-14] lint | Full wiki rebuild

- Nuked outdated session/playback/narration wiki; rebuilt for play-centric catalog + pure recommend

## [2026-07-18] update | Focus + Taste recommend module

- Implemented pure [recommend module](entities/recommend-module.md): `recommend_block`, `advance_focus`, `resolve_session_start`, tops rank-softmax seed
- Updated [recommendation blocks](concepts/recommendation-blocks.md) for Focus + Taste; empty neighborhood ends block early
- Orchestrator still `not_implemented` until wired
- Key takeaway: vibe walk in MuQ space with optional taste magnet; HTTP tops stay outside recommend

## [2026-07-18] update | Session wired to Focus + Taste

- `play` mints via tops + `resolve_session_start` + `recommend_block`; `need_next` advances focus and mints
- Session holds focus/taste/cooldown; foreign clears all
- Key takeaway: end-to-end DJ path live again (catalog → recommend → virtual queue → Connect)

## [2026-07-18] update | Architecture 1 + install path

- Renamed package `backend/` → `claude_dj/` (layered layout: session, catalog, recommend, playback, embeddings, integrate, daemon)
- Install: `install.sh` + `dj setup` (questionary); client ID in `~/.claude-dj/config.json`
- Session: two-block buffer; enter last block → mint one
- Updated overview + all concept/entity pages to new paths; Session page is `entities/session.md` (retired `orchestrator.md`)
- Key takeaway: product package matches Architecture 1; install no longer needs shell `export`

## [2026-07-18] lint | Post architecture wiki pass

- Fixed dangling `entities/orchestrator.md` link in log → `entities/session.md`
- Unresolved code-path footnotes expected (repo files are not wiki sources)