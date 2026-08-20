---
description: "Replace this caller's agent-defined menus on the Lux menu bar"
argument-hint: "<menus-json>"
allowed-tools: ["mcp__plugin_lux_lux__menu_set", "mcp__plugin_lux-dev_lux__menu_set", "mcp__lux__menu_set"]
---

# /lux:menu.set

Replace the caller's agent-defined menus on the Hub-owned menu bar. This is a full replace of the caller's slice, not an append — every prior menu this caller registered is dropped and the given list becomes the whole set. Each menu is `{"label": "...", "items": [{"label": "...", "id": "..."}]}`; a `"---"` label is a separator. Clicks arrive via `recv()` on the listener leg.

## Usage

- `/lux:menu.set [{"label":"Tools","items":[{"label":"Run","id":"run_btn"}]}]` — set this caller's menus to just Tools
- `/lux:menu.set []` — clear every menu this caller owns

## Implementation

Parse `$ARGUMENTS` as a JSON list of menu dicts. Call the `menu_set` MCP tool. The Hub replaces the caller's slice of the menu registry and the background replicator pushes the new bar to the display.
