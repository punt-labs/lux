# Changelog

## [Unreleased]

### Added

- **Display server** — ImGui-based visual output surface with non-blocking socket IPC
- **MCP server** — FastMCP tools (`show`, `update`, `clear`, `ping`, `recv`, `set_menu`)
  for AI agents to display text, tables, images, buttons, and interactive controls
- **Protocol** — framed JSON message protocol with element types: text, separator, image,
  button, table, markdown, group, collapsing_header, tab_bar, render_function
- **Interactive controls** — slider, checkbox, combo, text_input, radio, color_picker
  with event routing back to agents via `recv()`
- **Render functions** — `render_function` element kind for agent-submitted Python code
  with AST safety scanning, consent dialog, and sandboxed execution
- **Window chrome** — Always on Top, Borderless toggle, Opacity slider via Window menu
- **Auto-reconnect** — MCP tools automatically reconnect on broken pipe when display
  server restarts
- **Client library** — `LuxClient` context manager for Python callers
- **CLI** — `lux display` to launch the display server, `lux mcp` for MCP server

### Fixed

- Table columns use `WidthStretch` with `text_wrapped` for proper text wrapping
- Default status bar (Enable idling / FPS counter) hidden
- Reset Size menu item uses `change_window_size()` for runtime resize
- Markdown initialization warnings resolved by calling `initialize_markdown()` in post-init
- `ClearMessage` properly clears render function state
