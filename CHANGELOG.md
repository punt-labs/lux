# Changelog

## [Unreleased]

## [0.8.0] - 2026-03-10

### Added

- **SMP font coverage** — merge STIX Two Math (macOS) and Noto Sans Math
  (Linux) for Mathematical Alphanumeric Symbols block (U+1D400–1D7FF).
  Fixes diamond replacement glyphs for Z notation double-struck letters
  like 𝔽 (U+1D53D). See DES-020.
- **`make font-test`** — visual font coverage test that starts a dev display
  server for manual verification of SMP/BMP double-struck characters.
- **`lux show beads`** — CLI command that displays the beads issue board in
  the Lux window without requiring an LLM to generate the table mapping.
  Reads `.beads/issues.jsonl`, filters to active issues, and sends directly
  to the display server. Supports `--all` to include closed issues.
- **`copy_id` table flag** — when set, selecting a table row copies the first
  column value to the system clipboard. Enabled by default in `lux show beads`.
- **PostToolUse beads hook** — automatically refreshes the Lux beads board
  after `bd create`, `close`, `update`, `dep`, or `sync` commands.

## [0.7.2] - 2026-03-10

### Fixed

- **Draw element crash on RGBA list colors** — `_parse_hex_color` called
  `.lstrip()` on list inputs, raising `AttributeError` which escaped the
  draw command exception handler and killed the display server. Now accepts
  both hex strings and RGBA lists/tuples as documented in the MCP tool schema.

## [0.7.1] - 2026-03-10

### Fixed

- **Session start hook hang** — removed unnecessary stdin parsing from
  `cc_session_start`. The handler never used the data, so all 17 lines
  of non-blocking stdin reading were wasted work. See DES-027.

## [0.7.0] - 2026-03-09

### Added

- **Persistent dismissable tabs** — each `show()` call opens a new tab; multiple scenes coexist and users can dismiss them individually via close button. Same `scene_id` replaces content in-place (no new tab). Single-scene usage renders without tab bar chrome.
- **Flame idle screen** — animated candle flame with radial light rays replaces "waiting for scene..." text; theme-aware (adapts to light and dark backgrounds)
- **Clear All** menu item under Window — clears all tabs and resets to idle screen
- **Dock hiding** (macOS) — display server hides from Dock via `NSApplicationActivationPolicyAccessory`; process name shows as "Lux" in `ps` via `setproctitle`
- Optional `display` extras: `setproctitle`, `pyobjc-framework-Cocoa` (macOS only)

### Changed

- Default font scale increased from 1.0× to 1.1×
- Window title simplified from "Lux Display" to "Lux"

### Fixed

- **`/lux:beads` skill** — use `show_table` MCP tool instead of bypassing protocol with raw Python script via Bash

## [0.6.0] - 2026-03-09

### Added

- **`/lux y` and `/lux n` display mode toggle** — advisory L3 state signal for consumer plugins; persists to `.lux/config.md`
- **`display_mode` MCP tool** — get or set display mode (`y`/`n`) for LLM callers
- **`lux enable` / `lux disable` CLI commands** — terminal-facing display mode toggle
- **`lux hook session-start` CLI dispatcher** — SessionStart hook delegates to Python handler
- **`show_diagram()` MCP tool** — auto-laid-out architecture diagrams with layers, nodes, edges, and color-coded boxes via draw canvas
- **`/lux:diagram` skill** — guides agents through building layered box-and-arrow diagrams
- **Font size controls** — Increase Font / Decrease Font in Lux menu (0.5×–3.0× range)

### Changed

- Diagram layout: wider spacing, centred rows, edge port spreading, horizontal same-layer routing, angle-aligned arrowheads, edge label backgrounds

### Fixed

- Validate unique node IDs in diagram layout (raise `ValueError` on duplicates)
- Dynamic layer label column width based on longest label text
- Flip arrowhead direction for upward edges in diagrams
- Safe minimum canvas dimensions when all diagram layers are empty
- Skip empty-layer labels when computing label column width

## [0.5.2] - 2026-03-08

### Added

- **`show_table()` MCP tool** — filterable data tables with search, combo filters, and detail panel
- **`show_dashboard()` MCP tool** — metric cards, charts, and status tables in a single call
- **`set_theme()` MCP tool** — switch display theme (dark, light, classic, cherry)
- **`/lux:beads` skill** — rewritten as single-command recipe for beads issue board
- **`/lux:data-explorer` skill** — interactive filterable table with detail panel
- **`/lux:dashboard` skill** — metrics, charts, and status overview
- README screenshots: beads board, data explorer, dashboard

### Fixed

- Beads skill sort order: two-pass stable sort (updated_at desc, then priority asc)
- PyPI classifiers: added Python 3.14, fixed development status

## [0.5.1] - 2026-03-08

### Added

- **`install.sh`** — curl | sh installation script
- **`lux doctor`** — check for Unicode and symbol fonts
- **`lux install` / `lux uninstall`** — CLI commands per standard

### Changed

- Added acknowledgements for Dear ImGui, imgui-bundle, and FastMCP to README

## [0.5.0] - 2026-03-08

### Added

- **Display server** — ImGui-based visual output surface with non-blocking socket IPC
- **MCP server** — FastMCP tools (`show`, `update`, `clear`, `ping`, `recv`, `set_menu`)
  for AI agents to display text, tables, images, buttons, and interactive controls
- **Protocol** — framed JSON message protocol with element types: text, separator, image,
  button, table, markdown, group, collapsing_header, tab_bar, render_function
- **Interactive controls** — slider, checkbox, combo, input_text, radio, color_picker
  with event routing back to agents via `recv()`
- **Render functions** — `render_function` element kind for agent-submitted Python code
  with AST safety scanning, consent dialog, and sandboxed execution
- **Window chrome** — Always on Top, Borderless toggle, Opacity slider via Window menu
- **Auto-reconnect** — MCP tools automatically reconnect on broken pipe when display
  server restarts
- **Client library** — `LuxClient` context manager for Python callers
- **CLI** — `lux display` to launch the display server, `lux serve` for MCP server

### Fixed

- Table columns use `WidthStretch` with `text_wrapped` for proper text wrapping
- Default status bar (Enable idling / FPS counter) hidden
- Reset Size menu item uses `change_window_size()` for runtime resize
- Markdown initialization warnings resolved by calling `initialize_markdown()` in post-init
- `ClearMessage` properly clears render function state
