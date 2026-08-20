---
description: "Display a dashboard: metric cards, charts, and a summary table"
argument-hint: "<scene_id> [metrics=...] [charts=...] [table_columns=...] [table_rows=...]"
allowed-tools: ["mcp__plugin_lux_lux__scene_dashboard", "mcp__plugin_lux-dev_lux__scene_dashboard", "mcp__lux__scene_dashboard"]
---

# /lux:scene.dashboard

Compose the standard dashboard layout — metric cards across the top, charts in the middle, a summary table at the bottom. Any section is optional.

## Usage

- `/lux:scene.dashboard results metrics=[{"label":"Total","value":"142"}]` — metrics only
- `/lux:scene.dashboard results charts=[{"id":"c1","title":"Trend","series":[...]}]` — charts only
- `/lux:scene.dashboard results table_columns=[...] table_rows=[...]` — table only

## Implementation

Parse `$ARGUMENTS` as a scene id and optional `key=value` pairs (`metrics`, `charts`, `table_columns`, `table_rows`, `title`, `frame_id`, `frame_title`). Call the `scene_dashboard` MCP tool. Series types: `line`, `bar`, `scatter`. Full argument shape: see the `scene_dashboard` tool description.
