---
description: "List active scenes and frames from the Hub's authoritative store"
argument-hint: ""
allowed-tools: ["mcp__plugin_lux_lux__scene_ls", "mcp__plugin_lux-dev_lux__scene_ls", "mcp__lux__scene_ls"]
---

# /lux:scene.ls

List every scene and frame the Hub is holding — scenes (id, element count, frame id, owners) and frames (id, title, scene count, scene ids, layout).

## Usage

- `/lux:scene.ls` — print the current scene and frame tables

## Implementation

Call the `scene_ls` MCP tool with no arguments and report the result verbatim.
