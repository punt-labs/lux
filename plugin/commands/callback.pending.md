---
description: "Peek at the caller's held callback invocations without draining them"
argument-hint: ""
allowed-tools: ["mcp__plugin_lux_lux__callback_pending", "mcp__plugin_lux-dev_lux__callback_pending", "mcp__lux__callback_pending"]
---

# /lux:callback.pending

Report how many callback invocations the Hub is holding for this session. Peeks — the invocations stay queued; real delivery still runs on the listen leg's `take` drain.

## Usage

- `/lux:callback.pending` — print the pending count

## Implementation

Call the `callback_pending` MCP tool with no arguments and report the result verbatim. Expected shape: `"pending:<count>"`.
