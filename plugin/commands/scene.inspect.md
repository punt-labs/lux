---
description: "Return the element tree of a scene you own"
argument-hint: "<scene_id> [want_geometry=true]"
allowed-tools: ["mcp__plugin_lux_lux__scene_inspect", "mcp__plugin_lux-dev_lux__scene_inspect", "mcp__lux__scene_inspect"]
---

# /lux:scene.inspect

Read a scene you installed from the Hub's authoritative store — its element tree, each element's resolved state, and (optionally) painted screen rects.

## Usage

- `/lux:scene.inspect my-scene` — element tree only
- `/lux:scene.inspect my-scene want_geometry=true` — also include painted rects from the last frame

## Implementation

Parse `$ARGUMENTS` as a scene id, plus an optional `want_geometry=true|false` flag. Call the `scene_inspect` MCP tool. An unknown or unowned scene is a `not_found` error — you can only inspect scenes you installed (DES-086).
