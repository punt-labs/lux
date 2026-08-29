---
description: "Update elements in a scene without replacing everything"
argument-hint: "<scene_id> <patches-json>"
allowed-tools: ["mcp__plugin_lux_lux__scene_update", "mcp__plugin_lux-dev_lux__scene_update", "mcp__lux__scene_update"]
---

# /lux:scene.update

Patch elements in an existing scene. Each patch targets one element by id and either sets fields or removes it.

## Usage

- `/lux:scene.update my-scene [{"id":"t1","set":{"content":"Updated"}}]` — change text on element `t1`
- `/lux:scene.update my-scene [{"id":"b1","remove":true}]` — remove element `b1`

## Implementation

Parse `$ARGUMENTS` as a scene id followed by a JSON list of patches. Call the `scene_update` MCP tool. Report `"shown:<scene_id>"` on success, or `"error: scene not updated — <reason>"`.
