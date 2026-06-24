# Claude DJ Design

## Design summary

Claude DJ uses a local daemon because the music session needs to keep running after a single Claude Code command returns. The daemon owns Spotify state, permissions, session state, mood analysis, and the agentic DJ loop.

The Claude Code plugin should stay thin. It receives `/dj` commands, sends them to the daemon, and displays responses. The daemon does the ongoing work.

## Daemon model

The daemon is a long-running local process. It can be started by `/dj start` if it is not already running. Once started, it can keep running across Claude Code sessions.

The daemon allows multiple Claude Code sessions to connect, but only one session can actively control Spotify at a time. If a second Claude Code session runs `/dj start` while another session is active, Claude DJ should explain that another session is active and require `/dj takeover` before control moves.

This gives `/dj stop`, `/dj detach`, and `/dj quit` different meanings. `/dj stop` ends active music automation. `/dj detach` disconnects the current Claude Code session. `/dj quit` shuts down the daemon process.

## Components

The Claude Code command layer receives `/dj` commands and talks to the local daemon. It should not own long-running state or run the mood model directly.

The local daemon owns the DJ session. It manages Spotify authentication, Spotify playback actions, local permission checks, mood analyzer lifecycle, user overrides, and decision history.

The mood analyzer runs locally. It converts camera or audio input into mood and energy signals that the daemon can use. Raw camera and audio data should stay local.

The Spotify adapter is the only MVP music adapter. It should hide Spotify API details behind music actions such as reading playback state, searching, queueing, skipping, starting playback, and selecting a device.

The DJ controller is the agentic decision layer. It receives structured state from the daemon and chooses what music action, if any, should happen next.

The session store records the active session, attached Claude Code clients, recent mood signals, recent Spotify actions, user overrides, and explanation history.

## Agentic decision loop

Claude DJ should not be a fixed rule table. The daemon should run a small agentic controller that observes state, decides whether to intervene, chooses a Spotify action, records the decision, and can explain the choice later.

The loop can be described as:

```text
observe mood, Spotify playback, and session state
interpret the current energy and music fit
decide whether a music action is needed
choose the next Spotify action
record the decision and reason
explain the decision if asked
```

The first version can keep this controller simple. It only needs enough judgment to choose between staying similar, changing direction, skipping, queueing, or asking the user.

## Privacy and safety

Claude DJ should ask for explicit permission before camera or microphone analysis starts. The product should make it clear when mood sensing is active and should provide a quick way to stop it.

Camera, microphone, and biometric-like mood data should be processed locally for MVP. The design assumes no remote mood analysis. If a future version sends any of this data elsewhere, that should require a separate design review and explicit user consent.

Spotify auth should be scoped to music control. Claude DJ should not request more Spotify access than it needs for playback, search, queueing, and current-state reads.

## Open design questions

- Which local model should analyze mood?
- Should MVP use camera only, microphone only, or both?
- How often should the daemon sample mood?
- How should Claude DJ decide that a mood signal is confident enough to act on?
- How should user preference history be stored?
- What local IPC channel should connect the Claude Code plugin to the daemon?
- What persistence format should the session store use?
