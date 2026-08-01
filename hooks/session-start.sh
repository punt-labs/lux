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

# ── Allow MCP tools and Skill() permissions in user settings ─────────
if command -v jq &>/dev/null && [[ -f "$SETTINGS" ]]; then
  TMPFILE="$(mktemp)"
  trap 'rm -f "$TMPFILE"' EXIT
  NEEDS_UPDATE=false

  # MCP tool glob
  if ! jq -e ".permissions.allow // [] | map(select(contains(\"$TOOL_PATTERN\"))) | length > 0" "$SETTINGS" >/dev/null 2>&1; then
    NEEDS_UPDATE=true
  fi

  # Skill() rules for deployed commands — listed explicitly so
  # scripts/check-skill-permissions.sh can verify by static grep.
  SKILL_RULES=(
    "Skill(lux)"
  )

  PLUGIN_RULES='['
  for rule in "${SKILL_RULES[@]}"; do
    if ! jq -e --arg r "$rule" '.permissions.allow // [] | map(select(. == $r)) | length > 0' "$SETTINGS" >/dev/null 2>&1; then
      NEEDS_UPDATE=true
    fi
    PLUGIN_RULES="${PLUGIN_RULES}\"${rule}\","
  done
  PLUGIN_RULES="${PLUGIN_RULES%,}]"

  if [[ "$NEEDS_UPDATE" == "true" ]]; then
    jq --arg glob "$TOOL_GLOB" --argjson skills "$PLUGIN_RULES" \
      '.permissions.allow = ((.permissions.allow // []) + [$glob] + $skills | unique)' \
      "$SETTINGS" > "$TMPFILE"
    mv "$TMPFILE" "$SETTINGS"
  else
    rm -f "$TMPFILE"
  fi
fi

# ── Launch this session's applets ────────────────────────────────────
# An applet is a session-bound program that owns an entry in the Lux menu and
# services its clicks directly — in milliseconds, with no poll and no turn of the
# model. luxd cannot do this work itself: launchd starts it with no PATH, no
# repository, and no credentials, while this session has all three.
#
# $PPID is the Claude Code process that ran this hook. The applet watches it and
# exits when it goes, so an applet never outlives its session — including when
# the session is killed rather than closed, which is the case a SessionEnd hook
# would miss. The Hub's lease sweeps the menu entry regardless.
if command -v lux-beads &>/dev/null; then
  LUX_APPLET_LOG="${TMPDIR:-/tmp}/lux-beads-$PPID.log"
  nohup lux-beads --session-pid "$PPID" >"$LUX_APPLET_LOG" 2>&1 &
  disown
fi

exit 0
