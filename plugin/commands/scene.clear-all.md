---
description: "Clear every scene you own"
argument-hint: ""
allowed-tools: ["mcp__plugin_lux_lux__scene_clear_all", "mcp__plugin_lux-dev_lux__scene_clear_all", "mcp__lux__scene_clear_all"]
---

# /lux:scene.clear-all

Remove every scene owned by this session from the Hub. Does not touch scenes owned by other agents.

## Usage

- `/lux:scene.clear-all` — clear all scenes owned by this session

## Implementation

Call the `scene_clear_all` MCP tool with no arguments. Use `/lux:scene.clear <id>` when you want to clear a single scene instead.
