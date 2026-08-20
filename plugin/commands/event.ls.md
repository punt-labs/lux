---
description: "Return the last N display interaction events"
argument-hint: "[count]"
allowed-tools: ["mcp__plugin_lux_lux__event_ls", "mcp__plugin_lux-dev_lux__event_ls", "mcp__lux__event_ls"]
---

# /lux:event.ls

List the last N interaction events from the display — button clicks, slider changes, combo selections, other user interactions. Default 50, max 200. Proxied over luxd's one connection to the display.

## Usage

- `/lux:event.ls` — last 50 events
- `/lux:event.ls 10` — last 10 events

## Implementation

Parse `$ARGUMENTS` as an optional integer count (default 50). Call the `event_ls` MCP tool with the count and report the result verbatim.
