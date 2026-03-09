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

ACTIONS=()

# ── Deploy top-level commands (prod mode only) ───────────────────────
# In dev mode, skip — prod plugin handles top-level commands.
# Skip *-dev.md files — dev commands use plugin namespace (lux-dev:foo-dev)
if [[ "$DEV_MODE" == "false" ]]; then
  DEPLOYED=()
  for cmd_file in "$PLUGIN_ROOT/commands/"*.md; do
    [[ -f "$cmd_file" ]] || continue
    name="$(basename "$cmd_file")"
    [[ "$name" == *-dev.md ]] && continue
    dest="$COMMANDS_DIR/$name"
    mkdir -p "$COMMANDS_DIR"
    if [[ ! -f "$dest" ]] || ! diff -q "$cmd_file" "$dest" >/dev/null 2>&1; then
      cp "$cmd_file" "$dest"
      DEPLOYED+=("/${name%.md}")
    fi
  done
  if [[ ${#DEPLOYED[@]} -gt 0 ]]; then
    ACTIONS+=("Deployed commands: ${DEPLOYED[*]}")
  fi
fi

# ── Allow MCP tools in user settings if not already allowed ──────────
if command -v jq &>/dev/null && [[ -f "$SETTINGS" ]]; then
  if ! jq -e ".permissions.allow // [] | map(select(contains(\"$TOOL_PATTERN\"))) | length > 0" "$SETTINGS" >/dev/null 2>&1; then
    TMPFILE="$(mktemp)"
    jq --arg glob "$TOOL_GLOB" '.permissions.allow = (.permissions.allow // []) + [$glob]' "$SETTINGS" > "$TMPFILE"
    mv "$TMPFILE" "$SETTINGS"
    ACTIONS+=("Auto-allowed lux MCP tools in permissions")
  fi
fi

# ── Build setup message from actions ─────────────────────────────────
SETUP_MSG=""
if [[ ${#ACTIONS[@]} -gt 0 ]]; then
  SETUP_MSG="Lux plugin first-run setup complete."
  for action in "${ACTIONS[@]}"; do
    SETUP_MSG="$SETUP_MSG $action."
  done
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
