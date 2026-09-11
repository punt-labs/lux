---
description: "Remove a frame and tear down its scenes on the Hub"
argument-hint: "<frame_id>"
allowed-tools: ["mcp__plugin_lux_lux__frame_remove", "mcp__plugin_lux-dev_lux__frame_remove", "mcp__lux__frame_remove"]
---

# /lux:frame.remove

Remove a Hub-owned frame. Every scene inside the frame is removed. Use `/lux:scene.clear` to remove one scene while keeping the frame open.

## Usage

- `/lux:frame.remove work` — remove the `work` frame and drop its scenes

## Implementation

Parse `$ARGUMENTS` as one frame id. Call the `frame_remove` MCP tool.
