#!/usr/bin/env bash
# Format lux MCP tool output for the UI panel.
#
# Two-channel display:
#   updatedMCPToolOutput  -> compact panel line (◻ prefix, max 80 cols)
#   additionalContext     -> full result for the model to reference
#
# No `set -euo pipefail` — hooks must degrade gracefully on
# malformed input rather than failing the tool call.

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name')
TOOL_NAME="${TOOL##*__}"
RESULT=$(echo "$INPUT" | jq -r '
  def unpack: if type == "string" then (fromjson? // .) else . end;
  if (.tool_response | type) == "array" then
    (.tool_response[0].text // "" | unpack)
  else
    (.tool_response | unpack)
  end
  | if type == "object" and has("result") then (.result | unpack) else . end
')

emit() {
  local summary="$1" ctx="$2"
  jq -n --arg summary "$summary" --arg ctx "$ctx" '{
    hookSpecificOutput: {
      hookEventName: "PostToolUse",
      updatedMCPToolOutput: $summary,
      additionalContext: $ctx
    }
  }'
}

# Error guard: if the result contains an error field, surface it directly.
ERROR_MSG=$(echo "$RESULT" | jq -r '.error // empty' 2>/dev/null)
if [[ -n "$ERROR_MSG" ]]; then
  emit "◻ error: ${ERROR_MSG}" "$RESULT"
  exit 0
fi

if [[ "$TOOL_NAME" == "show" ]]; then
  SCENE=$(echo "$RESULT" | sed -n 's/^ack://p')
  if [[ -n "$SCENE" ]]; then
    emit "◻ scene:${SCENE}" "$RESULT"
  else
    emit "◻ ${RESULT}" "$RESULT"
  fi
  exit 0
fi

if [[ "$TOOL_NAME" == "update" ]]; then
  SCENE=$(echo "$RESULT" | sed -n 's/^ack://p')
  if [[ -n "$SCENE" ]]; then
    emit "◻ updated:${SCENE}" "$RESULT"
  else
    emit "◻ ${RESULT}" "$RESULT"
  fi
  exit 0
fi

if [[ "$TOOL_NAME" == "set_menu" ]]; then
  emit "◻ menu set" "$RESULT"
  exit 0
fi

if [[ "$TOOL_NAME" == "set_theme" ]]; then
  THEME=$(echo "$RESULT" | sed -n 's/^theme://p')
  emit "◻ theme:${THEME}" "$RESULT"
  exit 0
fi

if [[ "$TOOL_NAME" == "clear" ]]; then
  emit "◻ cleared" ""
  exit 0
fi

if [[ "$TOOL_NAME" == "ping" ]]; then
  # Extract RTT from "pong:rtt=0.003s" format
  RTT=$(echo "$RESULT" | sed -n 's/^pong:rtt=//p')
  if [[ -n "$RTT" ]]; then
    emit "◻ pong rtt=${RTT}" ""
  else
    emit "◻ pong" ""
  fi
  exit 0
fi

if [[ "$TOOL_NAME" == "recv" ]]; then
  if [[ "$RESULT" == "none" ]]; then
    emit "◻ no event" ""
  elif [[ "$RESULT" == interaction:* ]]; then
    # Extract action:element_id from "interaction:element=X,action=Y,value=Z"
    ACTION=$(echo "$RESULT" | sed -n 's/.*action=\([^,]*\).*/\1/p')
    ELEM=$(echo "$RESULT" | sed -n 's/.*element=\([^,]*\).*/\1/p')
    emit "◻ ${ACTION}:${ELEM}" "$RESULT"
  else
    emit "◻ ${RESULT}" "$RESULT"
  fi
  exit 0
fi

# Fallback: full output in panel
jq -n --arg r "$RESULT" '{
  hookSpecificOutput: {
    hookEventName: "PostToolUse",
    updatedMCPToolOutput: $r
  }
}'
