---
description: "Ping the display server; report round-trip time"
argument-hint: ""
allowed-tools: ["mcp__plugin_lux_lux__ping", "mcp__plugin_lux-dev_lux__ping", "mcp__lux__ping"]
---

# /lux:ping

Send a ping to the display server through luxd and report the round-trip time. Fails loud if the display is unreachable.

## Usage

- `/lux:ping` — check display liveness

## Implementation

Call the `ping` MCP tool with no arguments and report the result verbatim. `ping` is the one slash without a noun prefix because it names its verb — the operation is the ping, no noun would clarify it.
