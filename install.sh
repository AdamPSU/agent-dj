#!/usr/bin/env bash
# Install Claude DJ: uv tool + interactive setup.
set -euo pipefail

REPO_URL="${CLAUDE_DJ_REPO:-git+https://github.com/AdamPSU/claude-dj-plugin}"
# Default branch is still an old scaffold without pyproject.toml.
# Install from algorithm-v1 until main ships the package.
REF="${CLAUDE_DJ_REF:-algorithm-v1}"

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
    # fresh uv install often drops env here
    . "$HOME/.local/bin/env" 2>/dev/null || true
  fi
  export PATH="${HOME}/.local/bin:${PATH}"
fi

command -v uv >/dev/null 2>&1 || die "uv not found after install; add ~/.local/bin to PATH"

spec="${REPO_URL}@${REF}"

info "Installing claude-dj (${spec})…"
uv tool install --force "$spec"

if ! command -v claude-dj >/dev/null 2>&1; then
  bin_dir="$(uv tool dir 2>/dev/null || true)"
  export PATH="${HOME}/.local/bin:${PATH}"
  if ! command -v claude-dj >/dev/null 2>&1; then
    info "claude-dj is installed but not on PATH."
    info "Try: uv tool update-shell"
    info "Then re-run: claude-dj setup"
    exit 0
  fi
fi

info "Running setup…"
exec claude-dj setup "$@"
