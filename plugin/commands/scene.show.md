---
description: "Display a scene in the Lux window"
argument-hint: "<scene_id> <elements-json> [title=...] [layout=...]"
allowed-tools: ["mcp__plugin_lux_lux__scene_show", "mcp__plugin_lux-dev_lux__scene_show", "mcp__lux__scene_show"]
---

# /lux:scene.show

Display a scene — a tree of typed elements — in the Lux window. Replaces the current window contents with the given elements.

## Usage

- `/lux:scene.show my-scene [{"kind":"text","content":"hello"}]` — render one text element under scene id `my-scene`
- `/lux:scene.show my-scene [...] title="My Panel" layout=columns` — with a title and a columns layout
- `/lux:scene.show my-scene [...] frame_id=work frame_title="Work"` — pin the scene into a named frame

## Implementation

Parse `$ARGUMENTS` as a scene id followed by an elements list (JSON) and optional `key=value` pairs (`title`, `layout`, `frame_id`, `frame_title`, `frame_size`, `frame_flags`, `frame_layout`, `frame_ttl_seconds`). Call the `scene_show` MCP tool. Report `"shown:<scene_id>"` on success, or the error string.

Element kinds and full argument shape: see the `scene_show` tool description — it is the manual.
