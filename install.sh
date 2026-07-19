#!/usr/bin/env bash
# Install Claude DJ: uv tool + interactive setup.
set -euo pipefail

# Pin ref until main ships the package (GitHub default branch is still old).
REPO="${CLAUDE_DJ_REPO:-https://github.com/AdamPSU/claude-dj-plugin}"
REF="${CLAUDE_DJ_REF:-algorithm-v1}"
# uv git source must include the ref in the URL (default branch has no pyproject).
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
  info "Then re-run: dj setup"
  exit 0
fi

# Drop legacy binary name if a prior install left it behind.
if command -v claude-dj >/dev/null 2>&1; then
  info "Note: legacy 'claude-dj' may still be on PATH from an older install; use 'dj'."
fi

info "Running setup…"
# curl|bash leaves stdin as the pipe (not a TTY). Attach setup to the
# controlling terminal so questionary prompts work.
if [ -r /dev/tty ] && [ -w /dev/tty ]; then
  exec dj setup "$@" </dev/tty >/dev/tty 2>&1
fi
info "No controlling terminal; run setup yourself:"
info "  dj setup"
exit 0
