# Changelog

## [Unreleased]

### Added

- **Push-based event handling** — `LuxClient` gains a background listener
  thread with callback registry for autonomous UI event dispatch.
  `on_event(element_id, action, callback)` registers handlers keyed by
  `(element_id, action)` tuples (following standard UI framework
  conventions). Fire-and-forget methods (`show_async`, `update_async`,
  `clear_async`) are safe to call from callbacks. The listener
  auto-restarts on reconnect when callbacks are registered. Existing
  pull-based `recv()` continues to work — unmatched events and acks
  route to their respective queues.
- **Frame minimize/restore** — the collapse triangle (▼) in frame title
  bars now minimizes to a bottom dock bar instead of collapsing in-place.
  Clickable pills in the dock bar restore frames, matching Pharo
  Smalltalk's taskbar pattern.
- **Dock bar** — a persistent bar at the bottom of the display shows all
  minimized frames as pills. Click to restore and focus. The bar only
  appears when frames are minimized.
- **Restore All** — World menu now shows "Restore All" when frames are
  minimized, complementing the existing "Minimize All".
- **Detached World menu** — World menu is now a floating panel triggered
  by clicking the background, matching Pharo Smalltalk's World menu
  pattern. Mirrors the full menu bar (Lux, Debug, Windows, Help) plus
  agent-registered items. Appears at click coordinates, supports
  pin/unpin, and auto-closes on item click when unpinned.
- **Debug menu** — new menu with "Dump Scene JSON" for inspecting
  current display state (frames, scenes, clients).
- **Help menu** — displays current Lux version.
- **Paged group layout** — `GroupElement` gains `layout="paged"` with
  `pages` and `page_source` fields. A combo's selected index controls
  which page of children is visible, all client-side with no MCP
  round-trips.
- **Windows menu: Collapse All, Expand All, Fit All** — Collapse
  minimizes all frames to dock, Expand restores them, Fit All tiles
  frames in a non-overlapping grid layout. Items are grayed out when
  not applicable.

### Changed

- **Menu bar reorganization** — menu bar is now Lux | Debug | Windows |
  Help. Theme, Always on Top, Borderless, and Opacity moved under
  Lux > Settings. Opacity changed from slider to preset submenu
  (25%, 50%, 75%, 100%). "Window" renamed to "Windows".

### Fixed

- **Markdown initialization** — use `addons.with_markdown=True` instead
  of manual `initialize_markdown()` to prevent "Markdown was not
  initialized" warning spam.

## [0.10.0] - 2026-03-12

### Added

- **Frame auto-focus** — frames automatically focus (brought to front)
  when they receive a scene update. Minimized frames are restored.
- **Table `row_select` event** — clicking a table row emits a
  `row_select` InteractionMessage with row index and data, routable
  through `recv()`. Rows are selectable when `copy_id` flag is set,
  even without a detail panel.
- **`frame_size` and `frame_flags` on `show()`** — frames accept an
  initial size hint `[width, height]` and ImGui window flags
  (`no_resize`, `no_collapse`, `auto_resize`). Size applies on first
  use only; users can still resize afterwards unless `no_resize` is set.
- **Lightweight install** — heavy display deps (imgui-bundle, numpy,
  Pillow, PyOpenGL) moved to `[display]` extra. `pip install punt-lux`
  now pulls only lightweight deps (~2 MB); consumers that only need
  `LuxClient` no longer pay for the 66 MB display stack. End users
  install with `pip install 'punt-lux[display]'`.

### Changed

- **Public API** — `CodeExecutor` and `RenderContext` removed from
  `punt_lux` top-level exports. These are display-internal and remain
  importable from `punt_lux.runtime` directly.
- **Beads sort order** — in-progress issues float to the top of the
  beads board regardless of priority.
- **SessionStart hook** — made async; display mode discovery deferred
  to first MCP tool call.

### Fixed

- **Stale beads board on empty results** — when all issues are closed
  or no active issues exist, the beads frame now shows "No active
  issues." instead of leaving stale data from the previous refresh.

## [0.9.0] - 2026-03-11

### Added

- **ConnectMessage client identity** — clients identify themselves by name
  during handshake. Protocol validates non-empty names. Display server
  tracks client names for menu namespacing and logging.
- **Frames with orphan model** — scenes can target named frames (ImGui
  child windows). Frames persist after their owner disconnects and can be
  adopted by new clients sending to the same `frame_id`. Per-project beads
  boards each get their own frame (`beads-lux`, `beads-vox`, etc.).
- **World menu with per-client namespaces** — hierarchical menu replaces
  the flat Tools menu. Each connected client gets its own submenu
  (named from ConnectMessage). Menu items are sorted alphabetically
  within each client submenu. Environment items (Minimize All, Close All)
  appear below client submenus.
- **RegisterMenuMessage protocol type** — MCP servers can register menu
  items via the `register_menu` wire message. Items are per-client,
  merged alphabetically, and auto-cleaned on disconnect. Item ID
  uniqueness is enforced across clients.
- **Routed menu event delivery** — World menu item clicks are sent only to
  the owning client, not broadcast. Non-menu and environment events
  continue to broadcast.
- **`register_tool` MCP tool** — register a menu item in the World menu.
  Clicks are routed only to the registering server via `recv()`. Items
  auto-replay on reconnect.
- **`LuxClient.register_menu_item()`** — client library method for World
  menu registration. Accumulates items and replays on reconnect.

### Changed

- **Per-project beads frames** — each project's beads board opens in its
  own frame (`Beads: lux`, `Beads: vox`, etc.) so multiple projects
  can coexist without overwriting each other.
- **Window size** — default window increased from 800x600 to 1200x800.
  Frames fill 75% of the content region on first use.
- **PostToolUse beads hook** — fires on any `bd` subcommand, not just
  mutations. `bd ready`, `bd list`, `bd show`, etc. now refresh the board.
- **Resizable table columns** — beads board tables now have `resizable`
  flag enabled; users can drag column borders to resize.

### Fixed

- **Narrow table columns collapsing** — short-content columns like "P"
  (priority) collapsed to near-zero width when stretched beside long
  columns. Column weight floor raised from 1.0 to 4.0.

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
