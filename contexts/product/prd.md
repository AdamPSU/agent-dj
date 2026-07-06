# Claude DJ PRD

## Product summary

Claude DJ is a Claude Code plugin companion that controls Spotify during coding sessions. It starts from Claude Code, runs through a local daemon, and uses a lightweight controller to decide what music should play next from playback state, user commands, and simple preferences.

Claude DJ does not write code. It is not a general Claude Code automation agent. It is a music companion for coding sessions.

## Problem

Coding sessions have changing energy. A user may start neutral, settle into focus, get stuck, become frustrated, or get energized by a breakthrough. Music often stays fixed unless the user stops working and adjusts it manually.

Spotify DJ already gives people a model for adaptive listening, but it is not controlled from a coding session. Claude DJ brings that idea into Claude Code by adapting Spotify playback while keeping control inside the developer workflow.

## Product goal

Claude DJ should keep the user's coding music aligned with the session without turning music control into extra work. The user should be able to start it, let it run, and override it when needed.

The first version should feel simple. It should prove that a Claude Code plugin can attach to a local DJ daemon, control Spotify, and make local music decisions without requiring mood detection.

## Current prototype state

Claude DJ is currently packaged as the `claude-dj` CLI plus a global OpenCode `/dj` command. End-user install is intended to be one-time from Git through `claude-dj-install`; the installer prefers `uv tool install` and falls back to `pipx install`. Runtime `/dj` commands call the installed CLI directly and do not depend on the project checkout or `uv run`.

The local daemon, Spotify playlist indexing, Deezer preview resolution, local MuQ embedding generation, SQLite catalog, status reporting, and playlist-gated recommendation block generation are wired together. The prototype uses `OpenMuQ/MuQ-large-msd-iter` locally and stores 1024-dimensional embeddings. The sync pipeline runs in small chunks, commits preview and embedding progress incrementally, and exposes readiness through `/dj status`.

Spotify playback orchestration is wired for `/dj start`. The command starts or attaches to the daemon, kicks off catalog sync, waits until at least 30 tracks are ready when possible, generates a recommendation block, hydrates the selected internal track ids to Spotify URIs, and interrupts current playback with `PUT /me/player/play`. If Spotify reports no active device, Claude DJ discovers available Spotify Connect devices and targets the saved preferred device when it is available. Without an available saved preference, it prints the numbered device list and asks the user to run `/dj device <number>` before retrying `/dj start`. After the first block starts, a daemon playback monitor polls Spotify every 5 seconds and appends a fresh independent block with `POST /me/player/queue` when the known Claude DJ sequence has two tracks left after the current track. Spotify does not expose a queue-clearing API, so Claude DJ appends to the queue rather than promising to clear or replace the user's visible queue.

## User experience

The user starts Claude DJ from Claude Code with `/dj start`. The plugin connects to a local daemon or starts one if it is not running. The daemon handles Spotify authentication, session state, and music decisions.

Once started, Claude DJ runs in the background. It watches Spotify playback state and responds to user commands. It can keep the current vibe, queue similar music, change direction, skip, or ask the user for input. Optional mood detection can be added later, but baseline DJ mode should not depend on it.

The user stays in control through Claude Code commands. Planned controls include stopping automation, skipping, steering the vibe, detaching the current Claude Code session, taking over from another session, or quitting the daemon.

## Implemented command surface

- `/dj`: show daemon and catalog status.
- `/dj spotify-login`: run Spotify PKCE login and save the local token cache.
- `/dj start`: start or attach to the local DJ daemon, sync the catalog, and interrupt Spotify playback with a generated DJ block when enough embedded tracks are ready.
- `/dj devices`: list Spotify Connect devices visible to the current account.
- `/dj device <number>`: save a preferred Spotify Connect device from the numbered device list.
- `/dj sync`: start or join local catalog sync without starting a DJ playback action.
- `/dj status`: show daemon, sync, catalog, readiness, model, and last-run details.
- `/dj quit`: shut down the local daemon.

## Planned command surface

- `/dj stop`: stop music automation for the active DJ session without necessarily shutting down the daemon.
- `/dj skip`: skip the current track and record that the user wanted a change.
- `/dj vibe`: steer the current music direction.
- `/dj detach`: disconnect this Claude Code session from the daemon without stopping the daemon.
- `/dj takeover`: make this Claude Code session the active controller when another session already controls Claude DJ.

## Non-goals

The MVP does not write or modify code. It does not act as a coding subagent. It does not require camera, microphone, biometric, or mood-analysis input. It does not support every music provider. Spotify is the only playback target for the first version.

The MVP also does not try to make multiple Claude Code sessions control music at the same time. Spotify playback is global enough that competing controllers would be confusing. The first version uses one active DJ session and explicit takeover.

## MVP acceptance criteria

- `/dj start` starts or attaches to a local daemon.
- The daemon can authenticate with Spotify.
- The daemon can read Spotify playback state and apply at least one playback action.
- The DJ controller can choose a music action from playback state, user commands, and simple preferences.
- `/dj stop` stops active automation.
- Two Claude Code sessions cannot control Spotify at the same time without explicit takeover.

## Current implementation gaps

- The Spotify adapter can start playback with `/me/player/play`, list available Spotify Connect devices, read current playback state, and add queue items, but it does not yet transfer playback or skip tracks.
- Recommendation responses expose internal track ids, roles, and distances. Playback responses hydrate the first selected track with user-facing title, artist, Spotify URI metadata, and targeted device metadata when `/dj start` had to select a device.
- Session control is minimal: `/dj start` overwrites the active session id with `local-cli`; explicit detach, takeover, and stop semantics are still planned.
- Persistent decision history is not implemented.

## Open product questions

- How much should Claude DJ speak during a session?
- Should `/dj vibe` accept free text, preset names, or both?
- Should the first Spotify strategy use playlists, tracks, artists, genres, recommendations, or a mix?
- What optional mood detection mode should be explored after the local DJ loop works?

## Recommendation algorithm

The target recommendation algorithm should be simple and based on local sound embeddings when a permitted preview or audio source is available. It is not an agentic loop.

V1 uses Spotify as the playback and catalog source of truth, but Spotify audio must not be used as the embedding source. Claude DJ resolves Spotify tracks to ISRCs, then uses only a configured provider that can resolve those ISRCs to analyzable preview or audio URLs. The current local prototype uses Deezer previews because they are technically low-friction for ISRC matching, but Deezer remains prototype-only and is not a clean product default without explicit rights.

The implemented prototype proceeds as follows:

1. Pick one Spotify playlist source that has embedded tracks available.
2. Pick one random embedded seed song from that playlist.
3. Choose nearby songs in MuQ embedding space.
4. Return a 3-8 song DJ block and mark those internal track ids as recently used for a 3-hour cooldown.
5. Hydrate the block to Spotify URIs and start playback immediately on `/dj start`.
6. Poll Spotify playback every 5 seconds and queue a fresh independent block when the known Claude DJ sequence has two tracks left after the current track.

The intended DJ product behavior can later add genre labels, transitions, voice narration, and set-level direction. Those behaviors should be designed after the first Spotify playback orchestration loop works.

The provider-gated embedding pipeline is:

1. Read Spotify playlist or playback metadata.
2. Extract each Spotify track's ISRC.
3. Resolve the ISRC through the selected preview or audio provider.
4. Fetch the prototype preview URL for matched tracks.
5. Generate a local MuQ embedding from the preview audio.
6. Store the embedding and matching metadata locally.
7. Use nearest-neighbor search over local embeddings to choose similar songs.

Tracks that cannot be matched to a permitted preview or audio source should be skipped for embedding. Claude DJ should still be able to play them through Spotify, but they should not participate in embedding-based similarity until a valid source is found.
