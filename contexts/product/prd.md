# Claude DJ PRD

## Product summary

Claude DJ is a Claude Code plugin companion that controls Spotify during coding sessions. It starts from Claude Code, runs through a local daemon, and uses a lightweight controller to decide what music should play next from playback state, user commands, and simple preferences.

Claude DJ does not write code. It is not a general Claude Code automation agent. It is a music companion for coding sessions.

## Problem

Coding sessions have changing energy. A user may start neutral, settle into focus, get stuck, become frustrated, or get energized by a breakthrough. Music often stays fixed unless the user stops working and adjusts it manually.

Spotify DJ already gives people a model for adaptive listening, but it is not controlled from a coding session. Claude DJ brings that idea into Claude Code by adapting Spotify playback while keeping control inside the developer workflow.

## Product goal

Claude DJ should keep the user's coding music aligned with the session without turning music control into extra work. The user should be able to start it, let it run, override it when needed, and ask why it made a choice.

The first version should feel simple. It should prove that a Claude Code plugin can attach to a local DJ daemon, control Spotify, and make explainable music decisions without requiring mood detection.

## User experience

The user starts Claude DJ from Claude Code with `/dj start`. The plugin connects to a local daemon or starts one if it is not running. The daemon handles Spotify authentication, session state, and music decisions.

Once started, Claude DJ runs in the background. It watches Spotify playback state and responds to user commands. It can keep the current vibe, queue similar music, change direction, skip, or ask the user for input. Optional mood detection can be added later, but baseline DJ mode should not depend on it.

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

The MVP does not write or modify code. It does not act as a coding subagent. It does not require camera, microphone, biometric, or mood-analysis input. It does not support every music provider. Spotify is the only playback target for the first version.

The MVP also does not try to make multiple Claude Code sessions control music at the same time. Spotify playback is global enough that competing controllers would be confusing. The first version uses one active DJ session and explicit takeover.

## MVP acceptance criteria

- `/dj start` starts or attaches to a local daemon.
- The daemon can authenticate with Spotify.
- The daemon can read Spotify playback state and apply at least one playback action.
- The DJ controller can choose a music action from playback state, user commands, and simple preferences.
- `/dj why` can explain the last meaningful action.
- `/dj stop` stops active automation.
- Two Claude Code sessions cannot control Spotify at the same time without explicit takeover.

## Open product questions

- How much should Claude DJ speak during a session?
- Should `/dj vibe` accept free text, preset names, or both?
- Should the first Spotify strategy use playlists, tracks, artists, genres, recommendations, or a mix?
- What is the minimum useful explanation for `/dj why`?
- What optional mood detection mode should be explored after the local DJ loop works?

## Recommendation algorithm

The first recommendation algorithm should be simple and based on sound embeddings. It is not an agentic loop.

V1 proceeds as follows:

1. Pick a genre and stick to it for the current set.
2. Pick one random song from that genre, then choose songs that are similar to that seed song in embedding space.
3. Play 3-5 songs from the current genre.
4. After that set is done, switch to a different genre.
5. If DJ voice is enabled, which it is by default, Claude narrates the genre transition like a DJ. The DJ voice is powered by Haiku for narration text and ElevenLabs for speech.
