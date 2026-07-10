# Recommendation Glue Teardown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Disconnect the preserved similarity recommender from production daemon and CLI behavior while retaining catalog sync, embedding generation, adapters, narration primitives, and isolated similarity tests.

**Architecture:** Keep `recommendation/similarity.py` unchanged and remove every production import, callback, route, state field, and presentation path that composes it into playback. `/dj start` becomes an immediate session-attach and background-sync command. The existing sync pipeline stays in `daemon.py` for this phase.

**Tech Stack:** Python 3.12+, standard-library HTTP server and client, SQLite with sqlite-vec, pytest, uv.

## Global Constraints

- Preserve `src/claude_dj/recommendation/similarity.py`, `src/claude_dj/recommendation/__init__.py`, and `tests/test_similarity.py` byte-for-byte from baseline commit `fbf21a3`.
- Preserve Spotify adapter operations, track hydration, narration modules, ElevenLabs synthesis, local audio playback, embedding generation, and stored vector data.
- Do not add a fallback recommendation or playback strategy.
- Do not retain `POST /recommendations/next` as a compatibility endpoint.
- Do not extract catalog sync from `daemon.py` in this change.
- Keep the teardown in one implementation commit after the baseline and design commits.

## File Map

- `src/claude_dj/daemon.py`: retain HTTP lifecycle and catalog sync; remove recommendation and generated-playback composition.
- `src/claude_dj/cli.py`: retain command transport and catalog output; remove recommendation/playback rendering.
- `src/claude_dj/storage/db.py`: retain catalog and vector storage; remove recommendation-runtime readiness fields and query.
- `tests/test_daemon.py`: retain daemon transport and sync tests; replace recommendation/playback tests with immediate-session tests.
- `tests/test_cli.py`: retain command/status tests; remove generated-playback presentation tests and add delayed auth-status coverage.
- `tests/test_storage.py`: remove deleted readiness-field assertions.
- `README.md` and `wiki/**/*.md`: describe the recommender as preserved but disconnected.
- `docs/superpowers/plans/2026-07-09-recommendation-glue-teardown.md`: implementation record.

---

### Task 1: Make Session Start Attach And Sync Only

**Files:**
- Modify: `tests/test_daemon.py`
- Modify: `src/claude_dj/daemon.py`

**Interfaces:**
- Consumes: existing `DaemonRequestHandler._start_sync_if_idle() -> dict[str, object]` and `CatalogStatus.to_json()`.
- Produces: `POST /session/start` response with `ok`, `message`, `active_session_id`, `catalog`, `indexing`, `onboarding`, and `sync` only.

- [ ] **Step 1: Replace recommendation session tests with immediate attachment tests**

Keep the existing server helpers and add focused assertions equivalent to:

```python
def test_session_start_attaches_and_starts_sync_without_waiting() -> None:
    indexing_started = threading.Event()
    release_indexing = threading.Event()

    def slow_indexer() -> IndexSummary:
        indexing_started.set()
        release_indexing.wait(timeout=2)
        return IndexSummary(
            catalog_status=CatalogStatus(source_count=1, track_count=1, embedding_count=0),
            playlist_count=1,
            track_count=1,
            skipped_track_count=0,
        )

    server = create_server(spotify_indexer=slow_indexer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        response = json_request(
            "POST",
            f"http://{host}:{port}/session/start",
            {"session_id": "test-session"},
        )

        assert response["ok"] is True
        assert response["active_session_id"] == "test-session"
        assert response["sync"]["status"] == "running"
        assert "recommendation" not in response
        assert "playback" not in response
        assert "minimum_ready_tracks" not in response
        assert indexing_started.wait(timeout=1)
    finally:
        release_indexing.set()
        stop_test_server(server, thread)
```

Add a second test that preloads `sync_status = "running"` and a live `sync_thread`, then asserts repeated session start does not replace that thread.

Add a route-removal test:

```python
def test_recommendations_next_is_not_a_daemon_route() -> None:
    server, thread = start_test_server()
    try:
        host, port = server.server_address
        with pytest.raises(urllib.error.HTTPError) as error:
            json_request("POST", f"http://{host}:{port}/recommendations/next", {})
        assert error.value.code == 404
    finally:
        stop_test_server(server, thread)
```

- [ ] **Step 2: Run the new daemon contract tests and confirm they fail**

Run the exact new test node IDs with `uv run pytest ... -v`. Expected failures are old response fields, recommendation route availability, or readiness waiting.

- [ ] **Step 3: Simplify `DaemonRequestHandler._handle_session_start`**

Implement this shape using the existing state and sync helpers:

```python
def _handle_session_start(self, body: dict[str, object]) -> None:
    session_id = str(body.get("session_id") or "local-cli")
    self.server.state.active_session_id = session_id
    self._start_sync_if_idle()
    self._send_json(
        200,
        {
            "ok": True,
            "message": "Claude DJ session attached.",
            "active_session_id": session_id,
            "catalog": self.server.state.catalog_status.to_json(),
            "indexing": self.server.state.sync_indexing,
            "onboarding": {
                "index_all_playlists": self.server.state.catalog_status.needs_spotify_index,
                "resolve_previews": self.server.state.catalog_status.needs_preview_resolution,
                "embed_tracks": self.server.state.catalog_status.needs_embeddings,
            },
            "sync": self._sync_status_json(),
        },
    )
```

Delete the `/recommendations/next` route and handler.

- [ ] **Step 4: Remove recommendation and generated-playback daemon composition**

Delete these categories completely from `daemon.py`:

- Recommendation imports, callable alias, state injection, generator closure, and generation helpers.
- `MIN_READY_TRACKS`, `TRACK_COOLDOWN`, readiness wait helpers, and recommendation error calculation.
- Track hydrator, playback starter, playback-state fetcher, queue appender, options setter, narration preparer/player, pause/resume callback injection.
- `PendingBridge`, `BridgeTransitionPlan`, generated queue state, monitor state, lookahead state, and cooldown state.
- Block playback, monitor, queue replenishment, lookahead, bridge transition, automatic narration, playback response, and playback cleanup helpers.
- Playback and narration imports used only by deleted daemon composition.

Keep catalog schema initialization, Spotify indexing, preview resolution, embedding generation, sync chunking, runtime file handling, status, sync, and quit.

- [ ] **Step 5: Run daemon tests**

Run: `uv run pytest tests/test_daemon.py -v`

Expected: all retained and replacement daemon tests pass with no recommendation or generated-playback fixtures remaining.

---

### Task 2: Remove Recommendation Readiness And CLI Playback Presentation

**Files:**
- Modify: `tests/test_storage.py`
- Modify: `src/claude_dj/storage/db.py`
- Modify: `tests/test_cli.py`
- Modify: `src/claude_dj/cli.py`

**Interfaces:**
- Consumes: daemon status containing `catalog`, `sync`, and `indexing` without `playback`.
- Produces: catalog status without `ready_track_count` or `ready_for_audio_similarity`; CLI status that renders concrete counts and delayed indexing failures.

- [ ] **Step 1: Update storage expectations**

Change catalog serialization tests to assert these keys are absent:

```python
payload = get_catalog_status(db).to_json()
assert "ready_track_count" not in payload
assert "ready_for_audio_similarity" not in payload
```

Remove constructor arguments and direct assertions for deleted readiness fields.

- [ ] **Step 2: Run focused storage tests and confirm failure**

Run: `uv run pytest tests/test_storage.py -v`

Expected: failures identify the still-present readiness fields.

- [ ] **Step 3: Remove readiness storage code**

Delete `CatalogStatus.ready_track_count`, `CatalogStatus.ready_for_audio_similarity`, their JSON keys, and `_ready_track_count`. Stop querying ready tracks in `get_catalog_status`. Preserve all embedding counts and `needs_onboarding` behavior.

- [ ] **Step 4: Replace CLI playback tests with thin presentation tests**

Remove tests for the 600-second timeout, playback success, playback device suffixes, playback failures, and playback monitor output.

Add status auth guidance coverage equivalent to:

```python
def test_status_prints_spotify_login_guidance_after_background_auth_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "claude_dj.cli.get_json",
        lambda runtime_info, path: {
            "sync": {"status": "completed"},
            "catalog": {},
            "indexing": {
                "spotify": {
                    "ran": False,
                    "error_code": "spotify_auth_required",
                    "message": "Spotify login is required.",
                }
            },
        },
    )
    output = io.StringIO()
    write_status_details(get_json_payload(), output)
    assert "Spotify login is required." in output.getvalue()
    assert "Run: /dj spotify-login" in output.getvalue()
```

Use the test file's existing monkeypatch and response patterns rather than introducing `get_json_payload` if no such helper exists.

- [ ] **Step 5: Simplify the CLI**

Delete `SESSION_START_TIMEOUT_SECONDS`, pass the normal short `post_json` timeout from `start`, and remove:

- `write_playback_status`
- `_playback_device_suffix`
- `write_playback_monitor_status`
- recommendation-specific `write_readiness_status`
- `playback` handling in `write_status_details`

Keep `write_start_details`, but make it print the attachment response and song-storage message without trying to render playback.

Add one small indexing-error renderer used by status:

```python
def write_spotify_indexing_error(indexing: dict[str, object], stdout: TextIO) -> None:
    spotify = _dict_value(indexing, "spotify")
    error_code = spotify.get("error_code")
    if error_code not in {"spotify_auth_required", "spotify_access_denied"}:
        return
    message = spotify.get("message")
    if isinstance(message, str) and message:
        stdout.write(f"{message}\n")
    if error_code == "spotify_auth_required":
        stdout.write("Run: /dj spotify-login\n")
```

Call it from `write_status_details` after sync status and before catalog details.

- [ ] **Step 6: Run focused CLI and storage tests**

Run: `uv run pytest tests/test_storage.py tests/test_cli.py -v`

Expected: all focused tests pass.

---

### Task 3: Update Runtime Documentation

**Files:**
- Modify: `README.md`
- Modify: `wiki/overview.md`
- Modify: `wiki/entities/claude-dj.md`
- Modify: `wiki/concepts/local-daemon-architecture.md`
- Modify: `wiki/concepts/session-control.md`
- Modify: `wiki/concepts/spotify-playback-orchestration.md`
- Modify: `wiki/concepts/recommendation-loop.md`
- Modify: `wiki/concepts/provider-gated-audio-embeddings.md`
- Modify: `wiki/roadmap.md`

**Interfaces:**
- Consumes: final runtime behavior from Tasks 1 and 2.
- Produces: documentation that distinguishes preserved primitives from active daemon behavior.

- [ ] **Step 1: Remove active-playback claims from README and entity pages**

Document `/dj start` as session attachment plus background song storage. Remove statements that it generates, narrates, queues, or starts blocks.

- [ ] **Step 2: Mark similarity as preserved but disconnected**

At the top of `wiki/concepts/recommendation-loop.md`, state that `similarity.py` remains an isolated implementation and is not imported by daemon or CLI production paths while the replacement is redesigned.

- [ ] **Step 3: Rewrite daemon and playback architecture pages**

Remove the recommendation endpoint, readiness threshold, generated queue, lookahead, and narration handoff from current-state diagrams and tables. Keep Spotify adapter capabilities clearly labeled as available primitives rather than daemon-owned behavior.

- [ ] **Step 4: Update roadmap and overview links**

Describe recommendation composition and playback orchestration as future redesign work. Keep provider and embedding research intact.

- [ ] **Step 5: Search for stale active claims**

Search markdown for `recommendation`, `DJ block`, `30 ready`, `lookahead`, and `queue`. Inspect every result and ensure any remaining wording is historical, preserved-code, adapter-capability, or future-work context.

---

### Task 4: Prove The Boundary And Commit

**Files:**
- Verify: `src/claude_dj/recommendation/similarity.py`
- Verify: `tests/test_similarity.py`
- Verify: all modified files from Tasks 1 through 3

**Interfaces:**
- Consumes: completed teardown.
- Produces: one verified teardown commit.

- [ ] **Step 1: Prove preserved recommendation files are unchanged**

Run:

```sh
git diff fbf21a3 -- src/claude_dj/recommendation/similarity.py tests/test_similarity.py
```

Expected: no output.

- [ ] **Step 2: Prove production wiring is absent**

Search `src/` for `generate_next_dj_block`, `RecommendationGenerator`, `recommendation_generator`, `/recommendations/next`, `PendingBridge`, `lookahead`, and `TRACK_COOLDOWN`.

Expected: recommendation implementation symbols may appear only inside `recommendation/similarity.py`; daemon and CLI have no matches.

- [ ] **Step 3: Run focused verification**

Run:

```sh
uv run pytest tests/test_similarity.py
uv run pytest tests/test_daemon.py tests/test_cli.py tests/test_storage.py
```

Expected: all tests pass.

- [ ] **Step 4: Run full verification**

Run:

```sh
uv run pytest
git diff --check
```

Expected: full suite passes except tests explicitly skipped for external integration requirements; diff check produces no output.

- [ ] **Step 5: Review and commit the teardown**

Inspect `git status`, the complete diff, recent history, and the staged manifest. Stage only the plan and teardown files, then commit:

```sh
git commit -m "remove recommendation runtime glue"
```
