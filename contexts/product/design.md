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

The local daemon owns the DJ session. It manages Spotify authentication, Spotify playback actions, local session control, user overrides, and decision history.

An optional future mood analyzer can run locally. It would convert camera or audio input into mood and energy signals that the daemon can use, but baseline DJ mode should not require it.

The Spotify adapter is the only MVP music adapter. It should hide Spotify API details behind music actions such as reading playback state, searching, queueing, skipping, starting playback, and selecting a device.

The DJ controller is the agentic decision layer. It receives structured state from the daemon and chooses what music action, if any, should happen next.

The session store records the active session, attached Claude Code clients, recent Spotify actions, user overrides, and explanation history.

## Agentic decision loop

Claude DJ should not be a fixed rule table. The daemon should run a small agentic controller that observes state, decides whether to intervene, chooses a Spotify action, records the decision, and can explain the choice later.

The loop can be described as:

```text
observe Spotify playback, user commands, and session state
interpret the current music fit
decide whether a music action is needed
choose the next Spotify action, if any
record the decision and reason
explain the decision if asked
```

The first version can keep this controller simple. It only needs enough judgment to choose between staying similar, changing direction, skipping, queueing, or asking the user.

## Privacy and safety

Camera, microphone, and biometric-like mood data are out of scope for baseline MVP. If optional mood mode is added later, this data should be processed locally by default. Any remote analysis should require a separate design review and explicit user consent.

Spotify auth should be scoped to music control. Claude DJ should not request more Spotify access than it needs for playback, search, queueing, and current-state reads.

## Open design questions

- How should user preference history be stored?
- What local IPC channel should connect the Claude Code plugin to the daemon?
- What persistence format should the session store use?
- What optional mood analyzer should be considered after baseline local DJ mode works?
