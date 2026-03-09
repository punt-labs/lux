---
name: diagram
description: >
  Display an architecture diagram in the Lux window with auto-laid-out boxes,
  arrows, and labels. Use when the user asks to "show architecture", "draw a
  diagram", "visualize the system", "show dependencies", "architecture diagram",
  or wants a visual overview of components and their relationships. Also
  triggered by "box and arrow diagram", "system diagram", "component diagram",
  or "dependency graph".
allowed-tools:
  - mcp__plugin_lux_lux__show_diagram
  - mcp__plugin_lux-dev_lux__show_diagram
  - mcp__lux__show_diagram
---

# /lux:diagram — Architecture Diagram

Display a layered architecture diagram with auto-layout in the Lux window.

## Step 1: Identify components

Analyze the system or codebase to identify:

- **Layers** — logical groupings rendered top-to-bottom (e.g., Frontend, Backend, Storage)
- **Nodes** — individual components within each layer (e.g., Web App, API Server, Database)
- **Edges** — connections between components across layers (e.g., "REST", "SQL", "gRPC")

Each node has:

- `id` — unique identifier (used in edge routing)
- `label` — display name shown in the box
- `detail` (optional) — subtitle shown below the label

## Step 2: Call show_diagram

Call the `show_diagram` MCP tool with the layers, nodes, and edges.

The tool handles all layout automatically — box sizing, spacing, arrow routing, color coding per layer, and safe margins. No manual coordinates needed.

## Step 3: Tell the user

After the tool returns `ack:<scene_id>`, tell the user the diagram is live. Each layer is color-coded and nodes are auto-sized to their content.

## Notes

- Layers render top-to-bottom. Put callers/clients at the top, infrastructure at the bottom.
- Edges route from the bottom-center of the source node to the top-center of the destination.
- Edge labels appear at the midpoint of the arrow.
- Empty layers are skipped. Layers with no nodes are harmless but produce no output.
- The color palette cycles through 6 colors (blue, orange, green, red, purple, teal).
