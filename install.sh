#!/bin/sh
# Install punt-lux — visual output surface for your AI coding assistant.
# Usage: curl -fsSL https://raw.githubusercontent.com/punt-labs/lux/<SHA>/install.sh | sh
set -eu

# --- Colors (disabled when not a terminal) ---
if [ -t 1 ]; then
  BOLD='\033[1m' GREEN='\033[32m' YELLOW='\033[33m' NC='\033[0m'
else
  BOLD='' GREEN='' YELLOW='' NC=''
fi

info() { printf '%b▶%b %s\n' "$BOLD" "$NC" "$1"; }
ok()   { printf '  %b✓%b %s\n' "$GREEN" "$NC" "$1"; }
warn() { printf '  %b!%b %s\n' "$YELLOW" "$NC" "$1"; }
fail() { printf '  %b✗%b %s\n' "$YELLOW" "$NC" "$1"; exit 1; }

MARKETPLACE_REPO="punt-labs/claude-plugins"
MARKETPLACE_NAME="punt-labs"
PLUGIN_NAME="lux"
PACKAGE="punt-lux"
EXTRAS="display"
VERSION="0.32.1"
BINARY="lux"

# --- Step 1: Prerequisites ---

info "Checking prerequisites..."

if command -v claude >/dev/null 2>&1; then
  ok "claude CLI found"
else
  fail "'claude' CLI not found. Install Claude Code first: https://docs.anthropic.com/en/docs/claude-code"
fi

if command -v git >/dev/null 2>&1; then
  ok "git found"
else
  fail "'git' not found. Install git first: https://git-scm.com/downloads"
fi

# --- Step 2: uv ---

info "Checking uv..."

if command -v uv >/dev/null 2>&1; then
  ok "uv already installed"
else
  info "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  if [ -f "$HOME/.local/bin/env" ]; then
    # shellcheck source=/dev/null
    . "$HOME/.local/bin/env"
  elif [ -f "$HOME/.cargo/env" ]; then
    # shellcheck source=/dev/null
    . "$HOME/.cargo/env"
  fi
  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    fail "uv install succeeded but 'uv' not found on PATH. Restart your shell and re-run."
  fi
  ok "uv installed"
fi

# --- Step 3: Python 3.13+ ---

info "Checking Python..."

PYTHON_FLAG=""
HAVE_PYTHON=0
if command -v python3 >/dev/null 2>&1; then
  PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
  PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
  if [ "$PY_MAJOR" -gt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -ge 13 ]; }; then
    ok "Python ${PY_MAJOR}.${PY_MINOR}"
    HAVE_PYTHON=1
  fi
fi

if [ "$HAVE_PYTHON" = "0" ]; then
  info "Installing Python 3.13 via uv..."
  uv python install 3.13 || fail "Failed to install Python 3.13"
  ok "Python 3.13 (uv-managed)"
  PYTHON_FLAG="--python 3.13"
fi

# --- Step 4: Install lux CLI ---

info "Installing $PACKAGE..."

# shellcheck disable=SC2086
uv tool install --force $PYTHON_FLAG "${PACKAGE}[${EXTRAS}]==${VERSION}" || fail "Failed to install ${PACKAGE}[${EXTRAS}]==${VERSION}"
ok "$PACKAGE installed"

if ! command -v "$BINARY" >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v "$BINARY" >/dev/null 2>&1; then
    fail "$PACKAGE installed but '$BINARY' not found on PATH"
  fi
fi

ok "$BINARY $(command -v "$BINARY")"

# --- Step 5: Register luxd service ---
# 'hub install' is idempotent under launchd — it compares the plist it would
# write against what's already registered, and leaves an active, unchanged
# service alone rather than booting it out just to bootstrap the same thing
# back. The resolved binary path and args it writes are stable across
# versions, so a same-plist install() never touches a running daemon, and a
# bare install on an upgrade leaves the previous luxd process running with
# the previous bytecode. Restart afterwards so the running daemon matches
# the newly-installed wheel — but only on an upgrade. On a fresh install the
# daemon we would restart is the one 'hub install' just started, so the
# restart is redundant AND races the cold-load import of the [display]
# extras (imgui-bundle, numpy, Pillow) that pushes the ready-window past the
# restart's own timeout.

hub_was_running=0
if pgrep -x luxd-hub >/dev/null 2>&1; then
  hub_was_running=1
fi

display_was_running=0
if pgrep -x luxd-display >/dev/null 2>&1; then
  display_was_running=1
fi

info "Registering luxd service..."
"$BINARY" hub install || fail "Failed to register luxd service -- the plugin cannot reach luxd until it runs"
if [ "$hub_was_running" = "1" ]; then
  "$BINARY" hub restart || fail "Failed to restart luxd -- the running daemon still holds the previous bytecode"
fi

# --- Step 5b: Register the display service ---

info "Registering display service..."
"$BINARY" display install || fail "Failed to register display service -- the window will not appear until it runs"
if [ "$display_was_running" = "1" ]; then
  "$BINARY" display restart || fail "Failed to restart the display -- the running window still holds the previous bytecode"
fi

# --- Step 6: Health-check luxd ---

info "Waiting for luxd..."
_i=0
while [ $_i -lt 10 ]; do
  if curl -fs --max-time 3 http://127.0.0.1:8430/health >/dev/null 2>&1; then
    ok "luxd running"
    break
  fi
  sleep 2
  _i=$((_i + 1))
done
if [ $_i -eq 10 ]; then
  warn "luxd did not respond after 20s -- the plugin's HTTP endpoint may be unavailable until it starts"
fi

# --- Step 7: Register marketplace ---

info "Registering Punt Labs marketplace..."

if claude plugin marketplace list < /dev/null 2>/dev/null | grep -q "$MARKETPLACE_NAME"; then
  ok "marketplace already registered"
  claude plugin marketplace update "$MARKETPLACE_NAME" < /dev/null 2>/dev/null || true
else
  claude plugin marketplace add "$MARKETPLACE_REPO" < /dev/null || fail "Failed to register marketplace"
  ok "marketplace registered"
fi

# --- Step 8: SSH fallback for plugin install ---

# claude plugin install clones via SSH (git@github.com:...).
# Users without SSH keys need an HTTPS fallback.
NEED_HTTPS_REWRITE=0
cleanup_https_rewrite() {
  if [ "$NEED_HTTPS_REWRITE" = "1" ]; then
    git config --global --unset url."https://github.com/".insteadOf 2>/dev/null || true
    NEED_HTTPS_REWRITE=0
  fi
}
trap cleanup_https_rewrite EXIT INT TERM

if ! ssh -n -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=5 -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
  warn "SSH auth to GitHub unavailable, using HTTPS fallback"
  git config --global url."https://github.com/".insteadOf "git@github.com:"
  NEED_HTTPS_REWRITE=1
fi

# --- Step 9: Install or upgrade plugin ---

info "Installing $PLUGIN_NAME plugin..."

claude plugin uninstall "${PLUGIN_NAME}@${MARKETPLACE_NAME}" < /dev/null 2>/dev/null || true
if ! claude plugin install "${PLUGIN_NAME}@${MARKETPLACE_NAME}" < /dev/null; then
  cleanup_https_rewrite
  fail "Failed to install $PLUGIN_NAME"
fi
if ! claude plugin list < /dev/null 2>/dev/null | grep -q "$PLUGIN_NAME@$MARKETPLACE_NAME"; then
  cleanup_https_rewrite
  fail "$PLUGIN_NAME install reported success but plugin not found"
fi
ok "$PLUGIN_NAME plugin installed"

cleanup_https_rewrite

# --- Step 10: Verify ---

info "Verifying installation..."
printf '\n'
"$BINARY" version || true
printf '\n'

# --- Done ---

printf '%b%b%s is ready!%b\n\n' "$GREEN" "$BOLD" "$PLUGIN_NAME" "$NC"
printf 'Restart Claude Code to activate the plugin.\n'
printf 'The Lux display window opens automatically when agents send visual output.\n\n'
