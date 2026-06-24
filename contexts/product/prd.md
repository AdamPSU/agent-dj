# Claude DJ PRD

## Product summary

Claude DJ is a Claude Code plugin companion that controls Spotify during coding sessions. It starts from Claude Code, runs through a local daemon, reads the user's current mood through local camera or audio analysis, and uses an agentic controller to decide what music should play next.

Claude DJ does not write code. It is not a general Claude Code automation agent. It is a music companion for coding sessions.

## Problem

Coding sessions have changing energy. A user may start neutral, settle into focus, get stuck, become frustrated, or get energized by a breakthrough. Music often stays fixed unless the user stops working and adjusts it manually.

Spotify DJ already gives people a model for adaptive listening, but it is not aware of a coding session. Claude DJ brings that idea into Claude Code by adapting Spotify playback to the user's live state while keeping control inside the developer workflow.

## Product goal

Claude DJ should keep the user's coding music aligned with their mood and session energy without turning music control into extra work. The user should be able to start it, let it run, override it when needed, and ask why it made a choice.

The first version should feel simple. It should prove that a Claude Code plugin can attach to a local DJ daemon, control Spotify, and make explainable music decisions from local mood signals.

## User experience

The user starts Claude DJ from Claude Code with `/dj start`. The plugin connects to a local daemon or starts one if it is not running. The daemon handles Spotify authentication, camera or audio permissions, session state, and music decisions.

Once started, Claude DJ runs in the background. It watches local mood signals and Spotify playback state. When it has enough confidence, it can keep the current vibe, queue similar music, change direction, skip, or ask the user for input. If the user is neutral, humming, singing, dancing, smiling, or bopping their head, Claude DJ should usually continue with similar music. If the user's mood shifts away from that positive or engaged state, Claude DJ may try a different direction.

The user stays in control through Claude Code commands. They can stop automation, skip, steer the vibe, ask why a choice was made, detach the current Claude Code session, take over from another session, or quit the daemon.

## Command surface

- `/dj start`: start or attach to the local DJ daemon and create the active DJ session.
- `/dj stop`: stop music automation for the active DJ session without necessarily shutting down the daemon.
- `/dj why`: explain the last meaningful music decision.
- `/dj skip`: skip the current track and record that the user wanted a change.
- `/dj vibe`: steer the current music direction.
- `/dj detach`: disconnect this Claude Code session from the daemon without stopping the daemon.
- `/dj takeover`: make this Claude Code session the active controller when another session already controls Claude DJ.
- `/dj quit`: shut down the local daemon.

## Non-goals

The MVP does not write or modify code. It does not act as a coding subagent. It does not upload camera, microphone, or biometric data for remote analysis. It does not support every music provider. Spotify is the only playback target for the first version.

The MVP also does not try to make multiple Claude Code sessions control music at the same time. Spotify playback is global enough that competing controllers would be confusing. The first version uses one active DJ session and explicit takeover.

## MVP acceptance criteria

- `/dj start` starts or attaches to a local daemon.
- The daemon can authenticate with Spotify.
- The daemon can read Spotify playback state and apply at least one playback action.
- The daemon can receive a local mood or energy signal.
- The DJ controller can choose a music action from mood and playback state.
- `/dj why` can explain the last meaningful action.
- `/dj stop` stops active automation.
- Two Claude Code sessions cannot control Spotify at the same time without explicit takeover.

## Open product questions

- How much should Claude DJ speak during a session?
- Should `/dj vibe` accept free text, preset names, or both?
- Should the first Spotify strategy use playlists, tracks, artists, genres, recommendations, or a mix?
- What is the minimum useful explanation for `/dj why`?
