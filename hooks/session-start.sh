#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SETTINGS="$HOME/.claude/settings.json"
COMMANDS_DIR="$HOME/.claude/commands"
PLUGIN_JSON="${PLUGIN_ROOT}/.claude-plugin/plugin.json"

# Detect dev mode: plugin.json name contains "lux-dev"
DEV_MODE=false
if grep -q '"lux-dev"' "$PLUGIN_JSON" 2>/dev/null; then
  DEV_MODE=true
fi

if [[ "$DEV_MODE" == "true" ]]; then
  TOOL_PATTERN="mcp__plugin_lux-dev_lux__"
  TOOL_GLOB="mcp__plugin_lux-dev_lux__*"
else
  TOOL_PATTERN="mcp__plugin_lux_lux__"
  TOOL_GLOB="mcp__plugin_lux_lux__*"
fi

# ── Deploy top-level commands (prod mode only) ───────────────────────
# In dev mode, skip — prod plugin handles top-level commands.
# Skip *-dev.md files — dev commands use plugin namespace (lux-dev:foo-dev)
if [[ "$DEV_MODE" == "false" ]]; then
  for cmd_file in "$PLUGIN_ROOT/commands/"*.md; do
    [[ -f "$cmd_file" ]] || continue
    name="$(basename "$cmd_file")"
    [[ "$name" == *-dev.md ]] && continue
    dest="$COMMANDS_DIR/$name"
    mkdir -p "$COMMANDS_DIR"
    if [[ ! -f "$dest" ]] || ! diff -q "$cmd_file" "$dest" >/dev/null 2>&1; then
      cp "$cmd_file" "$dest"
    fi
  done
fi

# ── Allow MCP tools in user settings if not already allowed ──────────
if command -v jq &>/dev/null && [[ -f "$SETTINGS" ]]; then
  if ! jq -e ".permissions.allow // [] | map(select(contains(\"$TOOL_PATTERN\"))) | length > 0" "$SETTINGS" >/dev/null 2>&1; then
    TMPFILE="$(mktemp)"
    jq --arg glob "$TOOL_GLOB" '.permissions.allow = (.permissions.allow // []) + [$glob]' "$SETTINGS" > "$TMPFILE"
    mv "$TMPFILE" "$SETTINGS"
  fi
fi

# ── Ping display server (fire-and-forget, never blocks) ──────────────
# Wake up the display server if running. Short timeout ensures this
# completes quickly even if the server is unresponsive.
lux ping --timeout 1 >/dev/null 2>&1 || true

exit 0
