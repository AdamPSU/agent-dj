# Claude DJ

Claude DJ is a local Claude Code plugin companion that controls Spotify during coding sessions.

## Install

Claude DJ installs as a persistent local tool and adds a global OpenCode `/dj` command.

Install either `uv` or `pipx` first. `uv` is preferred. The installer will not install package managers for you.

```sh
uvx --from git+https://github.com/AdamPSU/claude-dj-plugin.git claude-dj-install
```

If you use `pipx` instead:

```sh
pipx run --spec git+https://github.com/AdamPSU/claude-dj-plugin.git claude-dj-install
```

The bootstrap command runs the installer from Git. The installer then uses `uv tool install` when `uv` is available, otherwise `pipx install`. Both install Claude DJ from the Git URL in an isolated persistent tool environment.

Create a Spotify developer app with redirect URI `http://127.0.0.1:8888/callback`, then export its client ID where OpenCode can read it:

```sh
export SPOTIFY_CLIENT_ID=<your-client-id>
```

Optional between-block DJ narration uses Claude Code Haiku for short scripts and ElevenLabs `eleven_v3` for local speaker playback. To enable it, also export these values or put them in `~/.claude-dj/.env`:

```sh
export ELEVENLABS_API_KEY=<your-elevenlabs-api-key>
export ELEVENLABS_VOICE_ID=<your-elevenlabs-voice-id>
```

Startup introductions are disabled for now to avoid delaying the first song. If between-block narration is not configured or fails, Claude DJ continues music without narration. Narration details and secrets are not shown in `/dj status`.

Claude DJ turns Spotify repeat off and shuffle off when starting playback so generated blocks play in deterministic order. It keeps one upcoming block generated, narrated, and queued ahead to tolerate fast song skipping.

After installing, restart OpenCode so the global command is loaded, then authenticate Spotify:

```text
/dj spotify-login
/dj start
```

## Development

This project uses `uv` for Python environment and dependency management.

```sh
uv sync
uv run pytest
```
