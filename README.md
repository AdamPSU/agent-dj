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
