#!/usr/bin/env bash
# Install Claude DJ: uv tool install, then print how to run setup.
# Setup is interactive (Spotify + MuQ) and must run in a real terminal —
# not via curl|bash stdin (that stream is the script pipe).
set -euo pipefail

REPO="${CLAUDE_DJ_REPO:-https://github.com/AdamPSU/claude-dj-plugin}"
REF="${CLAUDE_DJ_REF:-algorithm-v1}"
SPEC="git+${REPO}@${REF}"

info() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

os="$(uname -s 2>/dev/null || true)"
case "$os" in
  Darwin|Linux) ;;
  *) die "unsupported OS: ${os:-unknown} (macOS/Linux only)" ;;
esac

if ! command -v uv >/dev/null 2>&1; then
  info "Installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # shellcheck disable=SC1091
  if [ -f "$HOME/.local/bin/env" ]; then
    . "$HOME/.local/bin/env" 2>/dev/null || true
  fi
  export PATH="${HOME}/.local/bin:${PATH}"
fi

command -v uv >/dev/null 2>&1 || die "uv not found after install; add ~/.local/bin to PATH"

info "Installing dj (${SPEC})…"
uv tool install --force "${SPEC}"

export PATH="${HOME}/.local/bin:${PATH}"
if ! command -v dj >/dev/null 2>&1; then
  info "dj is installed but not on PATH."
  info "Try: uv tool update-shell && exec \$SHELL"
  info "Then run: dj setup"
  exit 0
fi

info ""
info "Installed. Complete setup in this terminal:"
info "  dj setup"
info ""
