---
description: "Show display server metadata: backend, resolution, FPS, PID, uptime"
argument-hint: ""
allowed-tools: ["mcp__plugin_lux_lux__display_info", "mcp__plugin_lux-dev_lux__display_info", "mcp__lux__display_info"]
---

# /lux:display.info

Read display server metadata from luxd — backend, resolution, FPS, PID, uptime.

## Usage

- `/lux:display.info` — print the current display info

## Implementation

Call the `display_info` MCP tool with no arguments and report the result verbatim.
