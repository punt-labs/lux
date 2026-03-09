#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SETTINGS="$HOME/.claude/settings.json"
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

SETUP_MSG=""

# ── Allow MCP tools in user settings if not already allowed ──────────
if command -v jq &>/dev/null && [[ -f "$SETTINGS" ]]; then
  if ! jq -e ".permissions.allow // [] | map(select(contains(\"$TOOL_PATTERN\"))) | length > 0" "$SETTINGS" >/dev/null 2>&1; then
    TMPFILE="$(mktemp)"
    jq --arg glob "$TOOL_GLOB" '.permissions.allow = (.permissions.allow // []) + [$glob]' "$SETTINGS" > "$TMPFILE"
    mv "$TMPFILE" "$SETTINGS"
    SETUP_MSG="Lux plugin first-run setup complete. Auto-allowed lux MCP tools in permissions."
  fi
fi

# ── Delegate to CLI handler for display mode context ─────────────────
HOOK_OUTPUT=$(echo '{}' | lux hook session-start 2>/dev/null) || true

if [[ -n "$SETUP_MSG" && -n "$HOOK_OUTPUT" ]]; then
  # Merge setup message into the hook output's additionalContext
  EXISTING=$(echo "$HOOK_OUTPUT" | jq -r '.hookSpecificOutput.additionalContext // ""')
  MERGED="${SETUP_MSG} ${EXISTING}"
  echo "$HOOK_OUTPUT" | jq --arg msg "$MERGED" '.hookSpecificOutput.additionalContext = $msg'
elif [[ -n "$SETUP_MSG" ]]; then
  cat <<ENDJSON
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "$SETUP_MSG"
  }
}
ENDJSON
elif [[ -n "$HOOK_OUTPUT" ]]; then
  echo "$HOOK_OUTPUT"
fi

exit 0
