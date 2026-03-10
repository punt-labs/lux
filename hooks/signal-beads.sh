#!/usr/bin/env bash
# hooks/signal-beads.sh — Refresh beads board after bd mutation commands.
#
# PostToolUse Bash — observation hook, fail-open.
# Detects bd create/close/update/dep/sync and refreshes the Lux display.

INPUT=$(cat)

# If jq is unavailable, fail open with no side effects.
command -v jq >/dev/null 2>&1 || exit 0

CMD=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null || echo "")

# Only trigger on bd mutation commands
[[ "$CMD" =~ (^|[;&|[:space:]])bd[[:space:]]+(create|close|update|dep|sync)([[:space:]]|$) ]] || exit 0

# Gate: .beads/ must exist in the repo
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[[ -d "$REPO_ROOT/.beads" ]] || exit 0

# Refresh the beads board (fire-and-forget)
(cd "$REPO_ROOT" && lux show beads 2>/dev/null) || true
