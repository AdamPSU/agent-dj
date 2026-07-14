# Playback Virtual Queue Design

**Date:** 2026-07-14  
**Status:** Draft for approval  
**Scope:** Real Spotify playback for Claude DJ, modeled on industry virtual-queue patterns (UpNext / Jammix SoT, Party-DJ poll+inject simplicity, Spartify track-change reconcile).  
**Depends on:** `backend/orchestrator.py`, `backend/recommend.py`, Fake `PlaybackPort`.

## Context

Claude DJ mints recommendation **blocks** and currently hands them to `FakePlayback`. Real Spotify control is finicky:

- No playback webhooks; must **poll** `GET /me/player`.
- Native queue is **append-only** (no reliable clear/remove/reorder).
- `GET /me/player/queue` is capped/unreliable; not a source of truth.
- Users can skip, pause, queue their own tracks, or change context at any time.

Industry party/DJ apps solve this with a **virtual queue owned by the app**, treating Spotify as a playback destination.

## Goals

1. Play orchestrator blocks on the user’s active Spotify device (Premium).
2. Survive **skips** and natural track ends without desync.
3. Detect **user takeover** (foreign track / context) and **yield** cleanly.
4. Keep `PlaybackPort` so tests keep using `FakePlayback`.
5. Stay local/single-user (no multi-guest voting complexity).

## Non-Goals (this design)

1. Editing or clearing Spotify’s native “Up Next” list.
2. Web Playback SDK / in-process audio (Connect control of existing devices only).
3. Gapless crossfade guarantees.
4. Multi-room / multi-user voting.
5. Narration (ElevenLabs) — later, between blocks.
6. Perfect millisecond progress UI.

## Product decisions (locked from research)

| Decision | Choice |
|----------|--------|
| Source of truth | **Virtual queue in daemon** (not Spotify queue) |
| Spotify write for DJ tracks | **`PUT /me/player/play` with `uris: [whole current block]`** (multi-URI) so Connect skip works |
| Native `addToQueue` | **Not used** — multi-URI play replaces the active context with our plan |
| Observation | Poll `GET /me/player` |
| Poll cadence | **5s** default; **2s** when `time_remaining < 30s` |
| Skip heuristic | Track id changed and previous progress ratio **&lt; 0.9** and remaining **≥ 30s** → `SKIPPED` |
| Natural advance | Track id changed and not skip → `ADVANCED` |
| User foreign track | Now-playing id ∉ expected set → **`YIELDED`** |
| Resume after yield | Explicit `/play` only (or future “resume DJ”) |
| Empty virtual queue | Mint next block via existing orchestrator/recommend path |
| Cooldown | Apply when a track is **committed** to play (same as fake: after successful start) and on skip/advance of planned tracks |

## Architecture

```text
                    recommend_block
                          │
                          ▼
                   Orchestrator
                   (session, cooldown, blocks)
                          │
                          ▼
                 VirtualQueue (ordered URIs)
                          │
              ┌───────────┴────────────┐
              ▼                        ▼
     SpotifyPlaybackPort         Monitor (tick)
     play(uri) / pause?          poll GET /me/player
              │                        │
              └──────── Spotify Connect device ────┘
```

### Layers

| Layer | Responsibility |
|-------|----------------|
| `recommend` | Pure block selection (unchanged) |
| `orchestrator` | Session, cooldown, mint blocks, call port, handle tick events |
| `playback` / port | Spotify HTTP: multi-URI start_block, read state; Fake for tests |
| `monitor` | Background loop while **ATTACHED**; emits events |

Daemon owns one orchestrator + one port + optional monitor thread (same process as catalog sync).

## Session modes

```text
IDLE ──play (ready)──► ATTACHED ──foreign track──► YIELDED
                         │  ▲                         │
                         │  └── explicit /play ────────┘
                         │
                         └── quit / stop ──► IDLE
```

| Mode | Behavior |
|------|----------|
| **IDLE** | No monitor; no auto play |
| **ATTACHED** | Virtual queue active; monitor ticks; auto-advance / mint |
| **YIELDED** | Monitor may still observe optionally, but **no** play/inject; user owns Spotify |

Pause does **not** leave ATTACHED; it only suppresses advance until `is_playing` again (or long pause policy later).

## Virtual queue

In-memory structure on the orchestrator (or port):

```text
VirtualQueue:
  items: list[{ track_id, spotify_id, uri, name, artists, ... }]
  index: int   # currently expected / playing planned track
  expected_id: str | None  # spotify id we last commanded or reconciled
```

On `start_block(tracks)`:

1. Replace or append virtual queue? **v1: replace** when starting from idle/cold; when auto-minting next block while ATTACHED, **append** to virtual queue then **multi-URI load only the new block**.
2. Set `index` to the new head, `expected_id = head.spotify_id`.
3. `PUT /me/player/play` with **all URIs in the new block** (not one track, not add-to-queue).
4. Apply cooldown for the current head only when it becomes current.

**Why multi-URI:** single-URI play leaves no next track for Spotify’s skip button. Loading the full block keeps virtual queue as SoT while giving Connect a real next list for *this* plan only.

**Near end of last track in plan:** mint next block early and multi-URI start it. Mid-block near-end does **not** re-issue play — Spotify advances the multi-URI list; monitor only reconciles.

## PlaybackPort (v1)

```text
Protocol PlaybackPort:
  start_block(tracks: list[Track]) -> None
      # set virtual queue, play first

  play_uri(spotify_id: str, *, device_id: str | None) -> None
      # PUT /me/player/play { uris: ["spotify:track:{id}"] }

  get_state() -> PlayerState | None
      # GET /me/player → normalized

  # optional later:
  # add_to_queue(spotify_id) 
  # pause() / resume() / next()  # next only if we choose to mirror user skip into Spotify

PlayerState:
  is_playing: bool
  progress_ms: int | None
  duration_ms: int | None
  track_id: str | None      # Spotify track id
  device_id: str | None
  context_uri: str | None
```

`FakePlayback` implements the same: updates an in-memory “now playing” for unit tests without HTTP.

## Monitor tick

Runs only in **ATTACHED** (and optionally YIELDED read-only for UI).

```text
every poll_interval:
  state = port.get_state()
  if state is None:          # no device / offline
    emit DEVICE_GONE; return
  if not state.is_playing:
    emit PAUSED; return

  if state.track_id != expected_id:
    if state.track_id in remaining_planned_ids:
      # user skipped ahead within our block or natural move
      reconcile_cursor(state.track_id)
      emit SKIPPED or ADVANCED
      play next if needed?  # if they skipped to our track N, set index=N; if past end, mint
    elif state.track_id is foreign:
      mode = YIELDED
      emit YIELDED
      return
    else:
      # unknown
      emit YIELDED

  else:
    # still on expected track
    if time_remaining < 30s:
      poll_interval = 2s
    if time_remaining < 5s and has_next_planned:
      # optional pre-buffer: NOT in v1 (play-one only)
      pass

  if natural end detected (id change + high progress) and has_next:
      advance_and_play_next()
  if queue empty after advance:
      mint next recommend block; append; play head
```

### Event → orchestrator actions

| Event | Action |
|-------|--------|
| `ADVANCED` | Move index; cooldown already applied at start of new current; if need next URI and nothing playing command pending, `play_uri(next)` |
| `SKIPPED` | Same as advanced for queue; mark skip for metrics later; cooldown for skipped track if not already |
| `YIELDED` | Stop monitor inject; set mode YIELDED; keep session embeds/cooldown |
| `PAUSED` | No mint/play |
| `DEVICE_GONE` | Stay ATTACHED but don’t thrash; surface in status |
| `QUEUE_EMPTY` | `recommend_block` with `next_block_seed`; append; play first of new block |

### Playing the next track

Because we use **single-URI play**, after a natural end Spotify may stop or autoplay something else. **v1 policy:**

1. Prefer detecting end via progress + short poll, then **immediately** `play_uri(next)`.
2. If Spotify autoplay inserts a foreign track before we act → **YIELDED** (safe).
3. Disable Spotify **shuffle**; set **repeat off** when attaching (best effort via Player API).

## `/play` semantics (updated)

| State | `/play` |
|-------|---------|
| IDLE + ready | Mint block → ATTACHED → start_block → start monitor |
| IDLE + not ready | kick sync + `not_ready` (unchanged) |
| ATTACHED | Idempotent snapshot (unchanged) |
| YIELDED | **Re-attach**: mint or continue queue? **v1: mint fresh block from next_block_seed if session embeds exist, else cold seed; clear virtual queue; ATTACHED** |

## `/status` additions

| Field | Meaning |
|-------|---------|
| `mode` | `idle` \| `attached` \| `yielded` |
| `playing` | Spotify reports playing (when known) |
| `now_playing` | `{spotify_id, name, artists, progress_ms, duration_ms}` or null |
| `virtual_queue` | Remaining planned tracks (ids/names), capped |
| `current_block` | Last minted block metadata (existing) |
| `indexed` / `recommend_ready` | Existing |

No readiness logging to stdout (statusline later).

## Spotify adapter additions

In `backend/adapters/spotify.py` (or `backend/playback/spotify_port.py`):

- `get_playback_state()`
- `start_playback(uris: list[str], device_id: str | None = None)`
- `transfer_playback` / `list_devices` as needed
- Active device: prefer currently active; else error `no_active_device`

Scopes already include modify/read playback state.

## Error handling

| Error | Response |
|-------|----------|
| No Premium / 403 | `play_failed` detail |
| No active device | `no_active_device` |
| 429 | Back off poll; don’t tight-loop play |
| Token expired | Existing refresh path |

## Testing strategy

1. **FakePlayback + Fake clock/state** — unit-test reconcile: advance, skip, yield, empty→mint.
2. **Orchestrator tests** — ATTACHED→YIELDED on foreign id; re-attach on `/play`.
3. **No live Spotify in CI.**

## Implementation phases

| Phase | Deliverable |
|-------|-------------|
| **P0** | This design approved |
| **P1** | `PlayerState`, port methods on Fake + Spotify; virtual queue on orchestrator; unit tests for reconcile |
| **P2** | Monitor thread in daemon; wire real port when not testing |
| **P3** | Status fields + device selection polish |
| **P4** (later) | Optional late `addToQueue` pre-buffer; narration hooks between blocks |

## Success criteria

1. `/play` with ≥50 indexed tracks starts audio on active device (manual e2e).
2. Skip within a block advances to next **planned** track without stalling.
3. User plays unrelated track → mode `yielded`; DJ stops injecting.
4. `/play` after yield starts a new DJ block.
5. Fake path keeps full unit coverage without network.

## Open decisions (defaults if unstated)

| Topic | Default |
|-------|---------|
| Append vs replace on re-attach | **Replace** with new block |
| Cooldown on skipped track | **Yes** (counts as played for 3h) |
| Monitor while YIELDED | **No** (save API quota) |
| Autoplay interference | Yield if foreign |

## References (research)

- UpNext: virtual queue SoT; sync only current track to Spotify; poll for manual changes.
- Party-DJ: 5s poll; inject in last ~35s via `addToQueue` + one-shot lock (we adopt poll/lock ideas, not queue-as-SoT).
- Spartify: 3s poll; retire on track-id change.
- Jammix: “Spotify is destination, not source of truth.”
- Spotify Player API: no remove-from-queue; command order not guaranteed; Premium required.
