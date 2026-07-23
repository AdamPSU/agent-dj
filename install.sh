#!/usr/bin/env bash
# Install Agent DJ: uv tool install, then print how to run auth.
set -euo pipefail

REPO="${AGENT_DJ_REPO:-https://github.com/AdamPSU/agent-dj}"
REF="${AGENT_DJ_REF:-main}"
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
  info "Then run: dj auth"
  exit 0
fi

info ""
info "Installed. Complete auth in this terminal:"
info "  dj auth"
info ""
