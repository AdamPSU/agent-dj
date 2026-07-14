# Spotify Auth Design

Date: 2026-07-14  
Status: approved for spec; implementation after user reviews this file

## Goal

Authorize a local Claude DJ user against Spotify once, then reuse tokens for later catalog and playback work.

This design is **auth only**. It does not implement playlist, history, or playback API calls.

## Nomenclature

| Term | Meaning |
|------|---------|
| CLI | Short-lived client (`claude-dj`); owns interactive login |
| Daemon | Long-lived FastAPI process; does **not** run OAuth UI |
| Adapter | Outbound integration with an external system (`backend/adapters/`) |
| PKCE | Proof Key for Code Exchange; Authorization Code flow without a client secret |

## Auth flow choice

**Authorization Code + PKCE** (public client).

| Flow | Fit |
|------|-----|
| Authorization Code + PKCE | Correct for user playlists, recently played, playback |
| Client Credentials | Wrong: no user context, no `/me/*` |
| Implicit | Deprecated / unsuitable |

- No client secret in the app.
- Client ID from environment only: `SPOTIFY_CLIENT_ID`.
- Access token ~1 hour; refresh token persisted for silent renew.

## Components

| Path | Responsibility |
|------|----------------|
| `backend/adapters/spotify.py` | PKCE, loopback callback, token load/save/refresh, `login()`, `get_access_token()` |
| `backend/config.py` | Spotify constants: env client id, scopes, token path, authorize/token URLs |
| `backend/cli.py` | `spotify-login` command; `start` gates on missing token file |
| Daemon | Unchanged for this design |

Layout:

```text
backend/
  adapters/
    spotify.py
  config.py
  cli.py
  daemon.py
```

No empty package stubs beyond what packaging requires.

## User flows

### Explicit login

```text
claude-dj spotify-login
  → require SPOTIFY_CLIENT_ID
  → bind free port on 127.0.0.1
  → open browser to Spotify authorize (PKCE S256)
  → handle GET /callback?code&state on that port
  → exchange code + code_verifier for tokens
  → write ~/.claude-dj/spotify_tokens.json (mode 0600)
  → print JSON { "ok": true, "path": "..." }
```

### Start gate

```text
claude-dj start
  → if token file missing: run login()
  → ensure daemon up
  → POST /start
```

Rules:

- Auto-login on `start` **only** when the token file is missing.
- Existing but expired tokens are **not** treated as missing; refresh is used when callers need an access token.
- Refresh failure does **not** auto-open the browser under this design; user runs `spotify-login` again.
- `status`, `sync`, and `quit` do not trigger login.

## Redirect URI

- Runtime redirect: `http://127.0.0.1:<ephemeral-port>/callback`
- Path is always `/callback`.
- Port is chosen free at login time (bind `127.0.0.1:0` or equivalent).
- Spotify Developer Dashboard must allow loopback redirects with dynamic ports for this app.
- Document dashboard setup in README when implementing.

## Token storage

Path: `~/.claude-dj/spotify_tokens.json`  
Permissions: `0600`

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": 1234567890.0,
  "scope": "...",
  "token_type": "Bearer"
}
```

- `expires_at` = now + `expires_in` − small skew (e.g. 30s).
- On refresh: save new access token; keep previous refresh token unless Spotify returns a new one.
- Never log tokens.
- Do not commit the token file.

## Scopes

Requested at authorize time (for later features; unused by auth-only code paths):

```
playlist-read-private
playlist-read-collaborative
user-read-recently-played
user-read-playback-state
user-modify-playback-state
```

Space-separated in the authorize query.

## Public adapter surface (v0)

```text
login() -> dict          # {ok, path}; interactive
get_access_token() -> str  # load; refresh if expired; error if no file
```

No playlist, history, or player methods in this design.

## Config surface

Add to `backend/config.py` (names illustrative; keep style consistent with existing constants):

- `SPOTIFY_CLIENT_ID` from `os.environ`
- `APP_DIR` = `~/.claude-dj`
- `SPOTIFY_TOKEN_PATH` = `APP_DIR / "spotify_tokens.json"`
- Authorize URL, token URL, scopes string
- No fixed redirect port constant required (ephemeral)

## Errors

| Condition | Behavior |
|-----------|----------|
| Missing `SPOTIFY_CLIENT_ID` | Non-zero exit, clear message |
| Login timeout / cancel / state mismatch | Non-zero exit |
| Token file missing when `get_access_token()` called | Non-zero exit; tell user to run `spotify-login` |
| Refresh hard failure | Surface error; do not auto-login on `start` if file exists |

## Out of scope

- Daemon OAuth routes or callback on the daemon port
- OS keychain
- Playlist / recently played / playback API
- Deezer
- Installer / OpenCode command changes
- Auth on `status` / `sync` / `quit`

## Testing

- PKCE S256 challenge matches verifier
- Token save/load and file mode `0600`
- `get_access_token` refreshes when `expires_at` is past
- Authorize path requires client id
- CLI: `spotify-login` invokes adapter login
- CLI: `start` calls login only when token file is missing (mocked)

## Implementation notes (non-binding)

- Prefer stdlib for HTTP token exchange and local callback server where practical.
- Browser open via standard library.
- Keep adapter free of FastAPI / daemon imports.
