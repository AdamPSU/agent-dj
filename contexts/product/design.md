# Claude DJ Design

## Design summary

Claude DJ uses a local daemon because the music session needs to keep running after a single Claude Code command returns. The daemon owns Spotify state, session state, user overrides, and the DJ loop.

The Claude Code plugin should stay thin. It receives `/dj` commands, sends them to the daemon, and displays responses. The daemon does the ongoing work.

## Current implementation state

The current prototype is an installed local CLI, daemon, and OpenCode command rather than a project-root script. `claude-dj-install` installs the package from Git with `uv tool install` or `pipx install` and writes a global OpenCode `/dj` command that shells out to `claude-dj`.

The daemon exposes a loopback JSON API and records its host, port, and PID in the local app directory. The local app directory also stores the SQLite catalog, Spotify token cache, and preferred Spotify device. The CLI can start the daemon, attach a session, trigger sync, show status, run Spotify login, list/select Spotify devices, and quit the daemon.

The catalog pipeline is wired through the daemon: Spotify playlists are indexed into SQLite, tracks are resolved by ISRC through Deezer previews, local MuQ embeddings are generated in 10-track chunks, and `/dj status` reports sync, catalog, readiness, model, and last-run details. The daemon starts sync in the background and can return once at least 30 tracks are ready for recommendation.

Playback orchestration is wired for `/dj start`. Recommendations are hydrated to Spotify URIs and sent to Spotify with `PUT /me/player/play`, which interrupts current playback on the active device. If Spotify reports no active device, Claude DJ lists available Spotify Connect devices and selects the saved preferred device only when it is currently available. Without an available saved preference, `/dj start` stops and tells the user to choose a device with `/dj device <number>` before retrying. After successful start, a background monitor polls Spotify playback every 5 seconds and queues a fresh independent block when the known Claude DJ sequence has two tracks left after the current track. Queue clearing, transfer playback, skip, and stop are not wired yet.

## Daemon model

The daemon is a long-running local process. It can be started by `/dj start` if it is not already running. Once started, it can keep running across Claude Code sessions.

The daemon allows multiple Claude Code sessions to connect, but only one session can actively control Spotify at a time. If a second Claude Code session runs `/dj start` while another session is active, Claude DJ should explain that another session is active and require `/dj takeover` before control moves.

This gives `/dj stop`, `/dj detach`, and `/dj quit` different meanings. `/dj stop` ends active music automation. `/dj detach` disconnects the current Claude Code session. `/dj quit` shuts down the daemon process.

## Components

The Claude Code command layer receives `/dj` commands and talks to the local daemon. It should not own long-running state or run DJ logic directly.

The local daemon owns the DJ session. It manages Spotify authentication, local session control, catalog sync, recommendation state, `/dj start` playback orchestration, and queue-ahead playback monitoring. Rich playback controls are still future milestones.

An optional future mood analyzer can run locally. It would convert camera or audio input into mood and energy signals that the daemon can use, but baseline DJ mode should not require it.

The Spotify adapter is the only MVP music adapter. It currently handles PKCE login, token refresh helpers, playlist reads, track normalization, ISRC extraction, available device reads, playback-state reads, queue appends, and starting playback from a list of track URIs with an optional device id. It should later hide Spotify API details behind music actions such as skipping and transferring playback.

The v1 DJ controller is a deterministic recommendation layer. It currently uses playlist membership and local audio embeddings to choose similar songs. User steering commands are planned but not implemented.

The audio embedding pipeline resolves Spotify tracks by ISRC, then fetches prototype previews from Deezer and generates local MuQ embeddings. Spotify remains the playback source of truth, but Spotify audio must not be used as the embedding source. Deezer is a prototype resolver, not a clean product default. Apple/iTunes is not a default provider because iTunes Search does not support documented ISRC lookup and Apple Music requires developer tokens.

The session store records the active session, attached Claude Code clients, recent Spotify actions, and user overrides.

## V1 recommendation loop

Claude DJ v1 should not use an agentic music-selection loop. The daemon should run a simple embedding-based controller that observes state, chooses similar music from the local vector index, and starts playback from the chosen block.

The loop can be described as:

```text
observe local embeddings, playlist sources, recent recommendation cooldowns, and session state
choose one playlist source with embedded tracks
pick a random seed song from that source
choose nearby songs in embedding space
return a 3-8 song DJ block
hydrate the block to Spotify URIs
interrupt current playback with `PUT /me/player/play`
poll playback every 5 seconds
when only two known queued tracks remain after the current track, generate and append another block
```

The first version should keep this controller simple. Today it generates playlist-coherent blocks, avoids recently recommended tracks for 3 hours, starts the generated block on the active Spotify device or an explicitly selected preferred Spotify device, and keeps playback going by appending independent blocks before the known sequence runs out. Any future agentic controller should be designed separately after the local daemon, Spotify playback, and embedding pipeline work.

## Privacy and safety

Camera, microphone, and biometric-like mood data are out of scope for baseline MVP. If optional mood mode is added later, this data should be processed locally by default. Any remote analysis should require a separate design review and explicit user consent.

Spotify auth should be scoped to music control. Claude DJ should not request more Spotify access than it needs for playback, search, queueing, and current-state reads.

## Open design questions

- How should user preference history be stored?
- What persistence format should the session store use?
- What optional mood analyzer should be considered after baseline local DJ mode works?
- Should future playback monitoring repair cases where user queue edits, skips, or Spotify queue behavior interrupt a DJ block after the first track?
