# Recommendation Glue Teardown Design

**Date:** 2026-07-09
**Status:** Approved for implementation planning

## Context

Claude DJ currently wires a deterministic embedding-similarity recommender directly into the local daemon. The daemon chooses recommendation blocks, waits for an embedding-count threshold, hydrates track IDs, starts Spotify playback, manages queue lookahead, tracks a cooldown, and coordinates narration between generated blocks. The CLI then presents recommendation and playback-specific responses.

This coupling makes the daemon and CLI responsible for recommendation policy and playback sequencing. The next recommendation system will be designed from scratch, so the existing production wiring should not become an implicit compatibility requirement.

The current recommendation implementation remains useful as underlying code. In particular, `src/claude_dj/recommendation/similarity.py` provides a working playlist-gated similarity implementation and generic nearest-neighbor behavior. This teardown preserves that file in place and keeps its focused tests. It removes only the production composition around it.

Before this design was written, the complete working tree was preserved in baseline commit `fbf21a3`.

## Goals

1. Disconnect the current recommendation implementation from all production daemon and CLI paths.
2. Make `/dj start` attach a session and launch or join background catalog sync without waiting for recommendation readiness.
3. Remove recommendation-dependent playback, queue, cooldown, lookahead, and narration orchestration from the daemon.
4. Remove recommendation and playback presentation logic from the CLI.
5. Preserve catalog indexing, preview resolution, MuQ embedding generation, vector storage, Spotify adapter operations, narration components, local audio playback, and device selection.
6. Preserve `recommendation/similarity.py` and its tests unchanged.
7. Leave the daemon's catalog-sync pipeline in place for this phase.

## Non-Goals

1. Do not design or implement the replacement recommendation system.
2. Do not refactor `recommendation/similarity.py` or move vector search to another package.
3. Do not extract catalog-sync orchestration from `daemon.py` in this change.
4. Do not remove Spotify playback adapter methods merely because the daemon no longer calls them.
5. Do not remove narration generation, ElevenLabs synthesis, or local audio playback.
6. Do not redesign the SQLite schema or delete stored embeddings.
7. Do not preserve the old recommendation endpoint as a compatibility stub.
8. Do not add a temporary fallback playlist or random playback strategy.

## Preserved Components

### Recommendation implementation

The following files remain unchanged:

- `src/claude_dj/recommendation/similarity.py`
- `src/claude_dj/recommendation/__init__.py`
- `tests/test_similarity.py`

The database helpers used by `similarity.py` also remain:

- `fetch_embedded_track_ids`
- `fetch_playlist_sources_with_embedded_tracks`
- `fetch_embedded_tracks_for_source`
- `PlaylistSourceCandidate`
- `EmbeddedTrackCandidate`

The implementation remains importable and testable, but no production entrypoint imports or invokes it.

### Catalog and embeddings

The following behavior remains active:

- Spotify playlist indexing into the local catalog.
- Deezer preview resolution by ISRC.
- Local MuQ embedding generation.
- Embedding model compatibility checks.
- SQLite vector and embedding metadata storage.
- Chunked preview and embedding processing.
- Catalog and sync status reporting.
- Explicit `/dj sync` behavior.

### Disconnected primitives

These capabilities remain in their existing modules for future composition:

- Spotify playback start, queue append, repeat, shuffle, pause, resume, and playback-state operations.
- Spotify device discovery and preferred-device selection.
- Track hydration from internal IDs to Spotify metadata.
- Narration prompt construction.
- Claude narration script generation.
- ElevenLabs speech synthesis.
- Local audio-file playback.

Keeping these modules does not imply that the daemon continues to coordinate them.

## Removed Production Wiring

### Recommendation injection

Remove the following daemon concepts:

- The `DJBlock` and `generate_next_dj_block` imports.
- The `RecommendationGenerator` callable alias.
- `DaemonState.recommendation_generator`.
- The `recommendation_generator` parameter to `create_server`.
- The `run_daemon` closure that opens SQLite and calls `generate_next_dj_block`.
- Recommendation generation helpers and in-memory cooldown tracking.

### Recommendation endpoint

Remove `POST /recommendations/next` and its handler. The daemon should route this path the same way as any unknown endpoint and return HTTP 404. No replacement unavailable response is introduced.

### Recommendation-dependent playback orchestration

Remove daemon state and functions whose only purpose is to execute or replenish generated DJ blocks:

- Minimum-ready-track gating and the 30-track threshold.
- Waiting for readiness before session-start responses.
- Recommendation block hydration and playback start.
- Generated queue tracking.
- Queue replenishment thresholds.
- Playback-monitor thread lifecycle.
- Lookahead recommendation generation.
- Track cooldown timestamps.
- Pending bridge state.
- Bridge transition timing and narration handoff.
- Automatic repeat and shuffle normalization for generated blocks.
- Automatic playback pause and resume for narration.
- Recommendation-specific playback and error response builders.

After removal, `run_daemon` no longer injects playback, queue, playback-state, narration, pause, or resume callbacks into the server. The source adapter and narration functions remain available outside daemon composition.

### CLI presentation

Remove presentation code that assumes `/dj start` starts a recommendation block:

- The 600-second session-start timeout intended to cover model loading and readiness waiting.
- Playback success and failure formatting.
- Device suffix formatting for automatic playback.
- Playback-monitor status formatting.
- Recommendation-specific readiness language.

The CLI remains responsible for parsing commands, locating or starting the daemon, making loopback HTTP requests, and rendering concise status information.

## Session Start Contract

### Request

`POST /session/start` continues to accept a JSON object with an optional `session_id`. Missing or empty values normalize to `local-cli`.

### Processing

The handler performs these steps in order:

1. Store the normalized active session ID.
2. Call the existing idempotent sync-start operation.
3. Return the current session, catalog, indexing, onboarding, and sync state immediately.

The handler does not wait for a track or embedding count. It does not call Spotify playback. It does not generate recommendations. It does not start playback-related background threads.

### Response

The successful HTTP 200 response contains:

- `ok: true`
- A session-attached message.
- `active_session_id`
- `catalog`
- `indexing`
- `onboarding`
- `sync`

The response does not contain placeholder `recommendation`, `playback`, `minimum_ready_tracks`, or recommendation-specific `error_code` fields.

### Repeated starts

Calling `/dj start` again updates the active session ID and joins the existing sync when one is running. It does not create a second sync thread. It does not inspect or attach to prior generated playback because generated playback is no longer daemon state.

## Error Handling

Session attachment succeeds independently of catalog readiness. Background sync owns indexing and embedding failures.

- Spotify authentication and access failures remain represented in the Spotify indexing payload.
- `/dj status` prints Spotify login guidance when the completed background indexing payload reports an authentication failure.
- Unexpected sync exceptions remain available through `sync.status = failed` and `sync.error`.
- Deezer rate limiting continues to stop the current chunk loop and remains visible through indexing status.
- `/dj status` remains the command for observing progress or failure after the immediate `/dj start` response.

The teardown must not convert background failures into swallowed exceptions. It only stops treating recommendation availability as a condition for session attachment.

## Catalog Status

Catalog counts for playlists, tracks, preview matches, pending previews, embeddings, and pending embeddings remain.

Remove `CatalogStatus.ready_track_count`, `CatalogStatus.ready_for_audio_similarity`, the `_ready_track_count` query, and their serialized fields. They exist to gate or describe the removed recommendation playback path. Keep `needs_onboarding` and its phase-specific properties because background sync still uses them. The CLI removes the `Readiness` section and continues to show concrete catalog counts and sync status.

No database migration is required. Existing embeddings and metadata remain valid.

## Testing Strategy

### Preserved tests

- Keep `tests/test_similarity.py` unchanged.
- Keep embedding, preview, storage, Spotify adapter, device, narration, and local playback tests unless a test directly asserts removed daemon composition.

### Daemon tests

Replace recommendation and generated-playback tests with focused transport and sync tests:

1. Session start claims the active session.
2. Session start launches background sync and returns without waiting for embeddings.
3. Session start joins an already-running sync without creating another worker.
4. Session-start responses omit recommendation and playback fields.
5. `POST /recommendations/next` returns 404.
6. Status continues to report catalog, sync, and indexing state.
7. Sync continues through Spotify indexing, preview resolution, and embedding chunks.
8. Spotify authentication and access errors remain visible through indexing state and `/dj status` guidance.
9. Quit still stops the server without playback-thread cleanup.

Tests dedicated only to generated playback, cooldowns, queue replenishment, lookahead, bridge timing, and daemon-owned narration are deleted with that behavior.

### CLI tests

Retain and adjust tests for:

1. Starting or attaching to the daemon.
2. Retrying after a stale daemon connection.
3. Rendering the session-attached and song-storage messages.
4. Rendering catalog and sync state.
5. Rendering Spotify indexing, preview, and embedding summaries.
6. Rendering Spotify authentication guidance from daemon status after background indexing reports the failure.
7. Explicit sync, status, device, login, and quit commands.

Delete tests for recommendation playback success, playback device targeting from `/dj start`, playback failure, playback monitoring, and the long recommendation-start timeout.

### Static boundary checks

After implementation, source searches must confirm:

- No production module imports `claude_dj.recommendation.similarity`.
- No production module calls `generate_next_dj_block`.
- No production route handles `/recommendations/next`.
- `recommendation/similarity.py` and `tests/test_similarity.py` remain unchanged from baseline commit `fbf21a3`.

### Verification commands

Run at minimum:

```sh
uv run pytest tests/test_similarity.py
uv run pytest tests/test_daemon.py tests/test_cli.py
uv run pytest
git diff --check
```

## Documentation Changes

Update documentation that currently describes the old wiring as active behavior:

- `README.md`
- `wiki/overview.md`
- `wiki/entities/claude-dj.md`
- `wiki/concepts/local-daemon-architecture.md`
- `wiki/concepts/session-control.md`
- `wiki/concepts/spotify-playback-orchestration.md`
- `wiki/concepts/recommendation-loop.md`
- `wiki/concepts/provider-gated-audio-embeddings.md`
- `wiki/roadmap.md` when it describes the old loop as currently wired

The recommendation-loop page should remain as a record of preserved underlying code, but it must say that the implementation is disconnected from daemon and CLI runtime behavior pending redesign. Playback-orchestration documentation should distinguish adapter capabilities from active daemon behavior.

## Expected File Changes

Implementation should be limited to these areas unless a test exposes a direct dependency that this design missed:

- `src/claude_dj/daemon.py`: remove recommendation and generated-playback composition; simplify session start and status.
- `src/claude_dj/cli.py`: remove recommendation/playback rendering and render delayed indexing errors through status.
- `src/claude_dj/storage/db.py`: remove recommendation-runtime readiness counts while preserving embedding and similarity storage helpers.
- `tests/test_daemon.py`: retain transport and catalog-sync coverage; remove generated-playback orchestration coverage.
- `tests/test_cli.py`: retain command and status coverage; remove generated-playback presentation coverage.
- `tests/test_storage.py`: remove assertions for deleted readiness fields.
- Documentation files listed above: mark the old recommendation wiring as disconnected.

`src/claude_dj/recommendation/similarity.py` and `tests/test_similarity.py` are explicit no-change files.

## Commit Structure

The work is separated into auditable commits:

1. `fbf21a3`: preserve the complete pre-teardown working tree.
2. Design/spec commit: record this approved boundary before code removal.
3. Teardown commit: remove production recommendation glue and update affected tests and documentation.

No unrelated cleanup belongs in the teardown commit.

## Acceptance Criteria

The teardown is complete when all of the following are true:

1. `/dj start` attaches a session, starts or joins background sync, and returns immediately.
2. `/dj start` never generates recommendations or controls Spotify playback.
3. The daemon exposes no recommendation endpoint.
4. The daemon contains no recommendation generator, cooldown, generated queue, lookahead, pending bridge, or generated playback-monitor state.
5. The CLI contains no recommendation playback or playback-monitor presentation logic.
6. Catalog indexing, preview resolution, embedding generation, and status reporting still work.
7. `recommendation/similarity.py` and its focused tests are unchanged.
8. Spotify playback and narration primitives remain in their existing modules and retain their focused tests.
9. Documentation no longer claims that daemon or CLI runtime paths use the old recommender.
10. The full test suite passes, excluding tests already marked to skip for external integration requirements.

## Deferred Work

The next recommendation design starts from explicit interfaces rather than reusing the deleted daemon contract. That future design must decide who owns selection policy, playback sequencing, feedback, narration timing, and daemon integration. This teardown intentionally leaves those questions open.
