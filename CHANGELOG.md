# Changelog

## [Unreleased]

### Added

- **Self-validating elements** — elements now check their own inputs. `show`
  decodes the element tree, then a hierarchy walk calls each element's
  `validate()` and collects *every* error across the tree (no fail-fast),
  recursing into every container (`group`, `window`, `modal`, `tab_bar`,
  `collapsing_header`, `tree`). An invalid tree is rejected before render and
  the full error set is returned to the agent so it can self-correct; a valid
  tree renders unchanged. Validation is component-appropriate and lives on the
  element: `TableElement.validate()` checks each row's cell count against the
  column count and that cells are renderable scalars — reporting, not crashing,
  when `columns`/`rows` arrive malformed; `TreeElement.validate()` checks its
  node structure instead of silently dropping malformed nodes. Contract:
  `SelfValidating` / `HasChildElements` protocols, a `ValidationError` value
  object, and a `ValidationReport` aggregate; the Element ABC supplies an
  empty-leaf default so every kind participates. A structural guard test fails
  if a new container kind is added without exposing its children, so nested
  elements can never silently skip validation. See DES-039.

### Fixed

- **No stacked display windows from a direct `lux display` or a concurrent
  spawn** — the display server now self-arbitrates at bind. `SocketServer.setup()`
  probes for a live display and exits cleanly if one is already serving,
  serializes its cleanup→bind→listen critical section under a dedicated bind-lock
  (distinct from the spawn lock, with a fixed spawn→bind acquisition order so the
  two can't deadlock), and treats a lost `bind()` race (`EEXIST`/`EADDRINUSE`) as
  "another instance won → exit 0" — the losing process exits before opening a
  window. The `listen()` backlog was raised (5→128) so a briefly-stalled display
  (not draining accepts) isn't misread as dead by a probe getting `ECONNREFUSED`
  on a full queue. (lux-h29e)

### Changed

- **Element-ABC renderer-factory DI made real and honest** — the Display now
  rebinds its real `ImGuiRendererFactory` onto every received ABC element (a new
  `Element.bind_renderer_factory`), so `Element.render()`'s dependency is
  production-wired rather than the fail-loud sentinel it silently carried. The
  renderer-factory docstrings were corrected to describe what the code actually
  does (they had claimed a decode-time factory threading that never happened),
  and the interactive remote-dispatch wrap was made Open-Closed via a per-element
  `RemoteDispatchSpec` hook (removing an `isinstance` switch and a domain→protocol
  layering inversion). Internal only — wire output byte-identical. Prerequisite
  for the render-path unification.
- **Table and layout element codecs moved onto their dataclasses** — the
  module-level `_<kind>_to_dict`/`_from_dict` functions became `to_dict`/
  `from_dict` methods (PY-OO-5), and the container-recursion dispatcher was
  extracted to `container_dispatch.py`. Wire output is byte-identical (132
  characterization snapshots unchanged).
- **`hub_*` path helpers promoted to a `HubPaths` class** (`hub_paths.py`),
  mirroring `DisplayPaths` — extracted from `paths.py`, no behavior change.
  (lux-bsrs)
- **Display lifecycle formally specified and model-checked** — `docs/display_lifecycle.tex`
  is a Z specification of the spawn/reap/bind concurrency, `fuzz`-clean and
  ProB-verified for singleton-serving, never-unlink-live, no-two-winners,
  lost-racer-clean-exit, and deadlock-freedom. A regression artifact for future
  lifecycle changes.

## [0.19.1] - 2026-07-04

### Changed

- **Starlette upgraded to 1.x** — `luxd` now requires `starlette>=1.3.1,<2`
  (was `>=0.46.0`), a major-version upgrade. The hub's WebSocket/HTTP app and
  the MCP transport run on Starlette 1.x; the MCP stack (mcp/fastmcp) imposes
  no upper bound, so it resolves cleanly. Verified: 1347 tests pass and luxd
  serves the MCP round-trip on 127.0.0.1:8430 under 1.3.1. Fresh `lux install`
  now resolves the patched 1.x rather than 0.x.
- **rich upgraded 13 → 15** (`rich>=15,<16`) — lux has no direct rich usage
  (only via typer's CLI output); `make check` and the CLI verified on 15.0.0.
- **imgui-bundle upgraded 1.92.600 → 1.92.801** — the display renderer.
  Verified live: the display spawns and renders (OpenGL3, ~47 fps, zero
  errors). This build ships `imspinner` and `imgui_md`, so the two
  previously-skipped renderer import tests now run and pass (1347 → 1349).

### Fixed

- **Display windows no longer accumulate; `make restart` reaps reliably** — the
  display singleton guard now reads liveness from the Unix socket (a tri-state
  connect/handshake probe) instead of a PID file, and resolves the running
  display's owner via the OS peer credential (macOS `LOCAL_PEERPID` / Linux
  `SO_PEERCRED`) so it is reaped regardless of how it was started. A stale or
  missing PID file can no longer orphan a live display or spawn a duplicate
  window. Spawn, reap, and cleanup are serialized under a single per-socket
  lock, and `make restart` now ensures exactly one live display (and fails
  loudly if one cannot start, instead of silently backgrounding a dead process).
  (lux-w8t5)

### Security

- **Cleared 17 Dependabot advisories.** Required `starlette>=1.3.1` (5 alerts:
  SSRF/NTLM via UNC paths, form-limit bypass, arbitrary HTTP-method dispatch,
  path concatenation, Host-header poisoning) and bumped the vulnerable
  transitive deps `pyjwt`→2.13.0, `python-multipart`→0.0.32, `cryptography`→49,
  `pydantic-settings`→2.14.2, `idna`→3.18 (12 alerts). Real exposure was low —
  luxd is localhost-only with CSWSH — but the dependency tree is now clean.
- **Least-privilege CI permissions** — the `test`, `lint`, and `docs` workflows
  now declare `permissions: contents: read` instead of inheriting the broad
  default `GITHUB_TOKEN` (clears 3 code-scanning alerts).

## [0.19.0] - 2026-07-03

This release is mid-migration, not a finished state. The Hub/Display io-model
and the OO decomposition are both **in progress**: only Text, Checkbox, and
Dialog elements are on the new Element ABC path, and `display/server.py` and
`display/element_renderer.py` remain over the module-size target. Entries below
describe what shipped, framed as increments.

### Changed

- **BREAKING — `set_display_mode` and `display_mode` MCP tools now require a
  `repo` argument** (absolute path of the caller's project). Config is
  read/written at `<repo>/.punt-labs/lux.md`. Previously the path resolved
  against the server process's cwd, which under launchd (cwd `/`) wrote to a
  read-only `/.punt-labs` and raised `[Errno 30]`. Callers must now pass their
  workspace path explicitly. (lux-r929)
- **Internal decomposition (ongoing, not complete)** — the original
  `display.py` (4,208 lines) was split into `display/`, `scene/`, `tools/`, and
  `protocol/` packages; `protocol.py`, `messages.py`, and `elements.py` became
  sub-packages; `MessageRegistry` and `ElementCodec` registries replaced
  if/elif dispatch. `display/server.py` (~1,400 lines) and
  `display/element_renderer.py` (~1,100 lines) are still above the 300-line
  target — further extraction remains.
- **Protocol dataclasses are `frozen=True, slots=True`**; draw-command `*Cmd`
  classes renamed to nouns (they are records, not commands).
- **Architecture spec refreshed** — `docs/architecture/system.tex` brought
  current: 24 element kinds, 24 MCP tools, frame architecture, introspection
  protocol. README MCP tool table expanded from 11 to the full 24-tool surface;
  `display_mode` documented as read-only alongside `set_display_mode`.

### Added

- **Initial Hub/Display io-model architecture** — Element ABC with two-tier
  handler dispatch, `HubDisplay` authoritative state, and a Hub-scoped Agent
  Subscribe publish/subscribe channel separate from the UI observer mechanism.
  Text, Checkbox, and Dialog elements are migrated to the ABC; remaining element
  kinds still use the legacy path. (lux-wb55, and the PR 0–4 migration chain)
- **Interactive checkbox** — fires a `ValueChanged` event through remote
  dispatch, routing the interaction back to the owning Hub. New `ValueChanged`
  event type; `RemoteDispatchGroup` widened from `ButtonClicked` to any `Event`.
- **Dialog modal clicks** — dialog buttons dispatch through the D21
  `remote_dispatch` path to the Hub's authoritative copy.
- **Typed draw-command decoder** — removes silent `.get()` defaults from the
  draw-command wire path. (lux-4n1b)
- **Concept papers from PR #109** — self-extending display vision
  (`concept-self-extending-display.md`), extension architecture
  (`concept-extension-architecture.tex`), and Working Backwards PR/FAQ
  (`concept-prfaq.tex`). Concept-stage exploration, not versioned roadmap.
- **Sub-agent write permissions** — `.claude/settings.json` allows Edit/Write
  for `src/`, `tests/`, `docs/`, `tools/`, `.tmp/` so background sub-agents can
  modify code without interactive approval.

### Fixed

- **luxd reads no display config at startup** — removed the MCP session
  lifespan's display-config gate and its eager-connect retry machinery. Under
  launchd the daemon runs with cwd `/`, so the gate's no-argument
  `ConfigManager()` resolved to a nonexistent `/.punt-labs/lux.md`: the read
  never matched the caller's project and the eager connect never fired. The
  gate was also redundant — `set_display_mode(y)` eager-connects on explicit
  enable and every tool call connects lazily. This eliminates both the
  read-only `/.punt-labs` failure class and the silently-disabled eager
  connect; luxd now holds no display-config state.
- **D21 remote dispatch: grouped handler wrapping** — `RemoteDispatchGroup`
  replaces per-handler wrapping so one button click yields one
  `RemoteEventHandlerInvocation` instead of N. Hub replays the full handler
  chain once on its authoritative copy.
- **D21 remote dispatch: owner resolution** — `_hub_interaction_dispatch` now
  resolves the real element owner from `HubDisplay.owner_of()` instead of
  hardcoded `"display-fallback"` sentinel.
- **D21 remote dispatch: race condition guard** — `owner_of` call moved inside
  the existing try/except block so a concurrent `drop_connection` cannot crash
  the dispatch handler.
- **D21 remote dispatch: PY-TS-10 compliance** — replaced `getattr` duck-typing
  in `_logical_handler_count` and `_is_remote_dispatch_group` with `isinstance`
  checks against `RemoteDispatchGroup`.
- **Display-tier publish safety** — `RaisingPublishSink` replaces
  `NoOpAgentSideSink` on the Display so misrouted publishes fail loud instead
  of silently dropping.
- **Hub scene replacement** — `HubDisplay.replace_scene` consolidates the
  remove-old + install-new loop from `tools.py` into the domain layer where
  ownership, root observers, and child indexes are rebuilt through `apply()`.
- **Coherent log-level control** — `LUX_LOG_LEVEL` now configures both the
  luxd hub and the display process; an invalid value warns instead of silently
  falling back.
- **launchd-aware `make restart`** — restarts both luxd (via launchd) and the
  separate display process, so code changes are actually picked up.
- **Beads auto-render hook** — uses `bd ready`, surfaces `bd` failures instead
  of swallowing them, and applies a 60s timeout.
- **Display restart on upgrade** — `lux install`/upgrade restarts the display
  so it does not keep running stale code.

### Removed

- **Dock-hiding behavior on macOS (macOS only)** — removed the
  `NSApplicationActivationPolicyAccessory` call in
  `DisplayServer._on_post_init`. The `lux-display` process now appears as a
  normal Dock app per GLFW's default activation policy, restoring standard
  macOS app presence and making operational debugging easier. Pairs with the
  v0.7.0 "Dock hiding" Added entry. No effect on Linux.

## [0.18.0] - 2026-05-12

### Changed

- **Canonical file and class renames** — `server.py` → `tools.py`,
  `client.py` → `display_client.py`, `LuxClient` → `DisplayClient`.
  Aligns module names with the distributed architecture proposal where
  `tools.py` holds MCP tool definitions and `display_client.py` is the
  client library for connecting to `lux-display`. `LuxClient` is
  available as a backward-compatible alias.

### Added

- **`luxd` session hub daemon** — WebSocket server (Starlette + uvicorn) that
  multiplexes MCP sessions onto a single display connection. Phase 1 of the
  distributed architecture: `/mcp` endpoint for mcp-proxy, `/health` for
  monitoring, CSWSH protection, session tracking. Managed by launchd (macOS)
  or systemd (Linux) with `KeepAlive=true`.

- **Hub CLI commands** — `lux hub-install`, `lux hub-uninstall`,
  `lux ensure-hub` (with `--restart`), `lux hub-status`, `lux setup-proxy`.

- **Session multiplexing in MCP tools** — `_session_key` ContextVar for
  per-session state isolation. Per-session menu registration tracking with
  cleanup on WebSocket disconnect. `run_mcp_session()` entry point for hub.

- **mcp-proxy config management** — `remote.py` reads/writes
  `~/.punt-labs/mcp-proxy/lux.toml` with atomic writes and 0600 permissions.

- **Generic query infrastructure** — `QueryRequest`/`QueryResponse` protocol
  types with generic dispatcher in the display server. Adding a new
  introspection operation now requires only a handler function and an MCP
  tool — no protocol changes. Existing `inspect_scene`, `list_scenes`,
  `screenshot` registered as query handlers alongside their dedicated paths.

- **mcp-proxy plugin fallback** — `plugin.json` tries mcp-proxy → luxd when
  `lux.toml` is configured, falls back to direct `lux serve`. `install.sh`
  adds mcp-proxy install, luxd service registration, and proxy config steps.

- **`inspect_scene` MCP tool** — query the display server for a scene's element
  tree as JSON. Enables agent self-debugging: see exactly what elements are
  rendered for a given scene_id without human intervention. Inspired by
  Postern's dashboard introspection pattern.

## [0.17.1] - 2026-05-11

## [0.17.0] - 2026-05-11

### Added

- **`make install` target** — builds wheel and installs locally with `[display]`
  extras, preventing the silent loss of display dependencies that occurs when
  running `uv tool install` on a bare wheel without extras.

- **`show_table` `frame_id`/`frame_title` parameters** — convenience wrapper
  now forwards frame parameters to `show()`, enabling tab-isolated tables
  (e.g., per-project beads boards) without falling back to raw `show()` calls.

### Changed

- **Beads browser fetches live data from DoltDB** — `load_beads()` now calls
  `bd list --json` via subprocess instead of reading the stale `.beads/issues.jsonl`
  file. The `/lux:beads` skill uses the Bash tool with `bd list --json` instead
  of the Read tool with JSONL files.

### Removed

- **Clock and Calculator applets** — removed along with the `render_function`
  element kind and consent dialog. Code-on-demand was a proof of concept; the
  core product is ImGui via JSON, not agent-submitted Python.
- **`show_diagram` MCP tool** — removed the 450-line auto-layout engine. ImGui
  has no native diagram support; this fought the framework. The `draw` element
  remains for custom 2D rendering.
- **`consent.py` and AST safety scanner** — only used by `render_function`.

### Fixed

- **Applications menu appears at display startup** — Beads Browser is registered
  by the display server at init,
  not by the MCP client on first tool call. The menu is visible immediately.

- **`/lux:beads` skill frame isolation** — skill now passes `frame_id` and
  `frame_title` to `show_table` so the beads board renders in its own frame
  instead of replacing the main scene.

## [0.16.1] - 2026-04-09

## [0.16.0] - 2026-04-09

### Added

- **Programmer Calculator applet** — multi-base integer calculator with bit grid,
  bitwise operations (AND/OR/XOR/NOT/shift), and computation history. Available
  via Applications > Calculator.
- **Analog Clock applet** — smooth-sweeping analog clock face with hour, minute,
  and second hands rendered via ImGui draw list. Transparent, borderless floating
  window. Available via Applications > Clock.
- **Frame flags `no_title_bar`, `no_background`, `no_scrollbar`** — new ImGui
  window flags for `frame_flags` on `show()`. Enable borderless/transparent frames.
- **`TextElement.color` field** — hex color string (e.g. `"#FF3333"`) for text
  elements, applied across all text styles.
- **TreeElement `flat` flag** — `flat=True` renders tree nodes without child
  indentation. Branch nodes use `NoTreePushOnOpen` for arrow+label toggle,
  leaf children render as flush-left selectable items. Useful for inline
  disclosure patterns where hierarchical indentation wastes horizontal space.
- **`InputNumberElement`** — numeric input field with optional step buttons,
  min/max clamping, and integer mode. Wraps `imgui.input_int`/`input_float`.
- **`ModalElement`** — modal popup dialog that blocks background interaction.
  Container element with children; emits `"closed"` event on user dismissal.
- **`ButtonElement` arrow/small variants** — `arrow` field renders directional
  arrow buttons (left/right/up/down); `small` field renders compact buttons.
- **`ColorPickerElement` alpha/picker modes** — `alpha=True` enables RGBA
  editing via `ColorEdit4`; `picker=True` renders full color picker widget.
- **Beads board sortable columns** — table now includes `sortable` flag.
- **`make depot` target** — builds the wheel and copies it to the local depot
  (`../.depot`) for cross-project dev iteration. Sibling projects that list
  the depot in `uv.toml` pick up the local wheel instead of the stale PyPI
  version.

### Fixed

- **PostToolUse hook stdin on Linux** — `signal-beads.sh` used `< /dev/stdin`
  which fails on Linux where `/bin/sh` is dash. The redirect opens
  `/proc/self/fd/0` as a separate file descriptor, losing pipe data. Removed
  the explicit redirect; stdin inherits naturally per hook standards § 3.
- **Debug scene dump flushing** — `Dump Scene JSON` menu item used `print()`
  without `flush=True`. With stdout redirected to a file (via `ensure_display`
  Popen), full buffering prevented the dump from reaching disk until process
  exit. Added `flush=True`.
- **Orphan scenes on disconnect** — scenes from a disconnecting client now
  persist instead of being dismissed. If another client shares the frame,
  ownership transfers; otherwise scenes are marked as orphans and the frame
  stays open until the user closes it or a new client adopts it. Fixes
  fire-and-forget CLI usage (`lux show beads`) where the beads frame would
  flash and disappear.
- **Eager connect retry with backoff** — MCP server lifespan retries the
  initial display connection up to 3 times (2s, 5s, 10s) instead of giving
  up silently on the first failure.
- **Development Status classifier** — reverted to `3 - Alpha` in `pyproject.toml`
  to match the project's actual stage.
- **TextElement tooltip hover** — tooltips on unstyled text elements now use
  `selectable()` for reliable hover detection. Styled text (heading, caption, code)
  uses the standard generic tooltip handler.

### Security

- **`cryptography` → 46.0.6, `pygments` → 2.20.0** — CVE-2026-34073,
  CVE-2026-4539.
- **`fastmcp` → 3.2.0** — CVE-2026-32871, CVE-2026-27124.
- **`PyJWT` ≥ 2.12.0** — high-severity vulnerability where the library
  accepted unknown `crit` header extensions.

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
