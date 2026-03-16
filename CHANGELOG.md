# Changelog

## [Unreleased]

## [0.15.1] - 2026-03-16

### Changed

- **Shared frame ownership** — frames now accept scenes from multiple clients.
  `owner_fd` replaced with `owner_fds: set[int]`. When a client disconnects,
  only its scenes are removed from the frame; other clients' scenes persist.
  Frames close when no scenes remain, regardless of connected owners.

## [0.15.0] - 2026-03-15

### Added

- **Frame stack layout** — new `frame_layout="stack"` option for multi-scene
  frames. Scenes render as vertically stacked collapsing headers (all visible,
  individually collapsible) instead of the default tab bar. Set via
  `frame_layout` parameter on `show()` / MCP `show` tool.

### Fixed

- **Updates no longer steal window focus** — `UpdateMessage` previously called
  `_focus_owning_frame`, raising the target frame to the front on every patch.
  With multiple frames receiving concurrent updates, this caused z-order
  fighting. Only `show` (scene creation) now raises frames.

## [0.14.2] - 2026-03-14

### Fixed

- **Markdown font size matches ImGui default** — `MarkdownElement` body text
  was noticeably larger because imgui_md loads its own Roboto fonts at 16px
  while Lux uses system fonts. Set `regular_size=13.0` via
  `with_markdown_options` (not `with_markdown=True`, which triggers a
  static guard that silently drops custom options). See DES-026.
- **Markdown text wrapping** — long lines now wrap at the parent container
  boundary via `push_text_wrap_pos(0.0)` instead of overflowing to the
  window edge.

### Changed

- **Base font size** — primary font increased from 15px to 16px for better
  readability at default scale.

## [0.14.1] - 2026-03-14

### Fixed

- **Eager connect now auto-spawns display server** — the `is_display_running()`
  guard prevented the MCP server from starting the display on session start,
  defeating the purpose of eager connect. Removed the guard and moved
  `_get_client()` to a background thread via `asyncio.to_thread()` so
  auto-spawn doesn't block the async event loop.
- **Thread safety for `_get_client()`** — added `threading.RLock` to prevent
  race conditions between the lifespan thread and MCP tool threads that
  could create duplicate `LuxClient` instances with leaked sockets.
- **Eager connect error visibility** — failures now log at `warning` level
  instead of `debug`, so users who set `display=y` can see why the display
  didn't start. Separated config-read errors from connect errors with
  distinct log messages.

## [0.14.0] - 2026-03-14

### Added

- **`lux ping` CLI command** — round-trip ping to the display server with
  configurable timeout (default 2s). Exits 0 on pong, 1 on timeout or no
  server. Does not auto-spawn the display server.
- **Eager connect on display=y** — the MCP server connects to the display
  server and registers applications immediately on startup when display
  mode is enabled, and again when `display_mode` is set to `y`. No more
  waiting for the first tool call.

### Fixed

- **Dock bar pill clicks broken by dock space** — `dock_space_over_viewport`
  covers the entire viewport, making the `is_window_hovered(any_window)`
  guard always true and blocking all pill clicks. Replaced with explicit
  per-frame hover tracking so pills only reject clicks when a visible
  frame window overlaps the dock bar.

## [0.13.0] - 2026-03-13

### Added

- **Beads Browser application** — the Applications menu now shows "Beads
  Browser" instead of "Hello World". Clicking it opens the beads issue
  board in a frame, same as the `/lux:beads` skill. The hook-based
  auto-refresh after `bd` commands continues to work alongside the menu
  entry.

### Changed

- **Extractable beads module** — `load_beads` and `build_beads_payload`
  moved from `show.py` to `apps/beads.py`, a self-contained module with
  no Lux display internals. Designed for future extraction into the beads
  repo as an optional dependency.

### Removed

- **Hello World demo app** — replaced by the Beads Browser application.

## [0.12.0] - 2026-03-13

### Added

- **Paged group Prev/Next buttons** — paged groups now render built-in
  `<< Prev` and `Next >>` buttons flanking the combo, wired directly to
  widget_state with no round-trip required.
- **ImGui docking** — frames can be drag-merged into tabbed dock nodes
  via `dock_space_over_viewport` and `DockingEnable` config flag.

### Fixed

- **imgui_bundle 1.92.600 compatibility** — replaced removed
  `style.colors[col.value]` API with `style.color_(col)`, fixing a
  crash in dock bar rendering.
- **imgui_bundle 1.92.600 docking regression** — docking was silently
  disabled in the new version; now explicitly enabled via config flag
  and viewport dock space.
- **Dock bar pill clicks** — replaced unreliable `invisible_button`
  inside an unfocused overlay window with raw mouse hit-testing, fixing
  click-to-restore on minimized frame pills.
- **Collapse vs dock conflict** — collapse-to-minimize no longer fires
  during ImGui docking transitions (`is_window_docked` guard).

### Changed

- **imgui-bundle pinned** — locked to `==1.92.600` to prevent future
  API breakage.

## [0.11.0] - 2026-03-13

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
- **Expand All / Collapse All** — Windows menu shows "Expand All" when
  frames are minimized and "Collapse All" when visible, for bulk
  minimize/restore.
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

- **Menu bar reorganization** — menu bar is now Lux | Applications | Debug |
  Windows | Help. Theme, Always on Top, Borderless, and Opacity moved under
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
