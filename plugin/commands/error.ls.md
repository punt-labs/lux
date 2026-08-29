---
description: "Return the last N display-side errors and warnings"
argument-hint: "[count]"
allowed-tools: ["mcp__plugin_lux_lux__error_ls", "mcp__plugin_lux-dev_lux__error_ls", "mcp__lux__error_ls"]
---

# /lux:error.ls

List the last N errors and warnings from the display. Each entry carries a timestamp, severity, message, and context. Default 20, max 100.

## Usage

- `/lux:error.ls` — last 20 errors
- `/lux:error.ls 5` — last 5 errors

## Implementation

Parse `$ARGUMENTS` as an optional integer count (default 20). Call the `error_ls` MCP tool with the count and report the result verbatim.
