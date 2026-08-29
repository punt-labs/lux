---
description: "Display a filterable data table with optional detail panel"
argument-hint: "<scene_id> <columns-json> <rows-json> [filters=...] [detail=...]"
allowed-tools: ["mcp__plugin_lux_lux__scene_table", "mcp__plugin_lux-dev_lux__scene_table", "mcp__lux__scene_table"]
---

# /lux:scene.table

Compose a searchable, filterable table with an optional drill-down detail panel — the common data-explorer pattern.

## Usage

- `/lux:scene.table issues ["ID","Title","Status"] [["ISS-1","Fix","Open"]]` — minimal table
- `/lux:scene.table issues [...] [...] filters=[{"type":"search","column":[0,1],"hint":"..."}]` — with a search filter
- `/lux:scene.table issues [...] [...] detail={"fields":[...],"rows":[...],"body":[...]}` — with a detail panel

## Implementation

Parse `$ARGUMENTS` as a scene id, a columns list (JSON), a rows list (JSON), and optional `key=value` pairs (`filters`, `detail`, `flags`, `key_column`, `table_id`, `title`, `frame_id`, `frame_title`). Call the `scene_table` MCP tool. Report `"shown:<scene_id>"` on success. Filter and detail shapes: see the `scene_table` tool description.
