# Claude DJ Design

## Design summary

Claude DJ uses a local daemon because the music session needs to keep running after a single Claude Code command returns. The daemon owns Spotify state, session state, user overrides, and the DJ loop.

The Claude Code plugin should stay thin. It receives `/dj` commands, sends them to the daemon, and displays responses. The daemon does the ongoing work.

## Daemon model

The daemon is a long-running local process. It can be started by `/dj start` if it is not already running. Once started, it can keep running across Claude Code sessions.

The daemon allows multiple Claude Code sessions to connect, but only one session can actively control Spotify at a time. If a second Claude Code session runs `/dj start` while another session is active, Claude DJ should explain that another session is active and require `/dj takeover` before control moves.

This gives `/dj stop`, `/dj detach`, and `/dj quit` different meanings. `/dj stop` ends active music automation. `/dj detach` disconnects the current Claude Code session. `/dj quit` shuts down the daemon process.

## Components

The Claude Code command layer receives `/dj` commands and talks to the local daemon. It should not own long-running state or run DJ logic directly.

The local daemon owns the DJ session. It manages Spotify authentication, Spotify playback actions, local session control, user overrides, recommendation state, and decision history.

An optional future mood analyzer can run locally. It would convert camera or audio input into mood and energy signals that the daemon can use, but baseline DJ mode should not require it.

The Spotify adapter is the only MVP music adapter. It should hide Spotify API details behind music actions such as reading playback state, searching, queueing, skipping, starting playback, and selecting a device.

The v1 DJ controller is a deterministic recommendation layer. It uses playlist metadata, user commands, and local audio embeddings when available to choose similar songs and record explainable decisions.

The audio embedding pipeline resolves Spotify tracks by ISRC, then fetches preview or audio only from a configured provider with acceptable rights for local analysis. Spotify remains the playback source of truth, but Spotify audio must not be used as the embedding source. Apple/iTunes is not a default provider because iTunes Search does not support documented ISRC lookup and Apple Music requires developer tokens.

The session store records the active session, attached Claude Code clients, recent Spotify actions, user overrides, and explanation history.

## V1 recommendation loop

Claude DJ v1 should not use an agentic music-selection loop. The daemon should run a simple embedding-based controller that observes state, chooses similar music from the local vector index, records the decision, and can explain the choice later.

The loop can be described as:

```text
observe Spotify playback, user commands, local embeddings, and session state
choose or keep the current genre direction
pick a seed song for that genre
choose nearby songs in embedding space
queue or play the next Spotify track, if any
record the decision and reason
explain the decision if asked
```

The first version should keep this controller simple. It should play short genre-coherent sets, choose songs near the current seed song in embedding space, and switch genres after a set is done. Any future agentic controller should be designed separately after the local daemon, Spotify playback, and embedding pipeline work.

## Privacy and safety

Camera, microphone, and biometric-like mood data are out of scope for baseline MVP. If optional mood mode is added later, this data should be processed locally by default. Any remote analysis should require a separate design review and explicit user consent.

Spotify auth should be scoped to music control. Claude DJ should not request more Spotify access than it needs for playback, search, queueing, and current-state reads.

## Open design questions

- How should user preference history be stored?
- What local IPC channel should connect the Claude Code plugin to the daemon?
- What persistence format should the session store use?
- What optional mood analyzer should be considered after baseline local DJ mode works?
