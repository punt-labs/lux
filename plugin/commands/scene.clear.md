---
description: "Clear one scene and blank its frame"
argument-hint: "<scene_id>"
allowed-tools: ["mcp__plugin_lux_lux__scene_clear", "mcp__plugin_lux-dev_lux__scene_clear", "mcp__lux__scene_clear"]
---

# /lux:scene.clear

Remove one scene you own from the Hub and blank the frame it was rendering in.

## Usage

- `/lux:scene.clear my-scene` — clear the scene id `my-scene`

## Implementation

Parse `$ARGUMENTS` as one scene id. Call the `scene_clear` MCP tool. An unknown scene, or one owned by someone else, returns an error — never a silent success.
