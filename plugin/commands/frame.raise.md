---
description: "Bring a frame to the front, restoring it if minimized"
argument-hint: "<frame_id>"
allowed-tools: ["mcp__plugin_lux_lux__frame_raise", "mcp__plugin_lux-dev_lux__frame_raise", "mcp__lux__frame_raise"]
---

# /lux:frame.raise

Raise a Hub-owned frame to the top of the window stack. If the frame was minimized, it is restored.

## Usage

- `/lux:frame.raise work` — bring the `work` frame to the front

## Implementation

Parse `$ARGUMENTS` as one frame id. Call the `frame_raise` MCP tool. An unknown frame returns an error.
