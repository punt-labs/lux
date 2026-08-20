---
description: "Add custom menus to the Lux display menu bar"
argument-hint: "<menus-json>"
allowed-tools: ["mcp__plugin_lux_lux__menu_set", "mcp__plugin_lux-dev_lux__menu_set", "mcp__lux__menu_set"]
---

# /lux:menu.set

Write a list of menus to the Hub-owned menu bar. Each menu is `{"label": "...", "items": [{"label": "...", "id": "..."}]}`; a `"---"` label is a separator. Clicks arrive via `recv()` on the listener leg.

## Usage

- `/lux:menu.set [{"label":"Tools","items":[{"label":"Run","id":"run_btn"}]}]` — add a Tools menu

## Implementation

Parse `$ARGUMENTS` as a JSON list of menu dicts. Call the `menu_set` MCP tool. The Hub writes the menu registry and the background replicator pushes the bar to the display.
