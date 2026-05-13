# Lux Refactoring Plan

**Related documents:**

- [`class-responsibility-report.md`](class-responsibility-report.md) — OO design analysis. Defines every class (existing and proposed), its single responsibility, compositions, collaborations, and the functions/methods that move into it. The design source of truth.
- [`class-responsibility-review.md`](class-responsibility-review.md) — Peer review of the design report by `rej` (Ralph Johnson). Verdict: GO with modifications. This plan incorporates those modifications.

**This document** is the executable refactoring plan. It combines the report's class designs with the review's feedback into step-by-step instructions that preserve behavior at every step.

Every step is a behavior-preserving transformation. `make check` passes
after every step. One class extraction per step -- never two at once.
Characterization tests are written BEFORE extraction, not after. Old
module-level functions become thin wrappers for backward compatibility.

---

## Invariants

These hold throughout the entire refactoring. Violations are bugs.

1. **No extracted class imports `DisplayServer`.** All upward
   communication uses `Callable` parameters set in the constructor.
   Enforce with an import linter or grep in CI:
   `grep -r 'from punt_lux.display import' src/punt_lux/scene_manager.py`
   must return nothing (and likewise for every new module).

2. **`make check` passes after every step.** Lint, type check (mypy +
   pyright), and all tests green. No exceptions.

3. **Backward compatibility via wrappers.** When a module-level function
   moves into a class, the old function stays as a thin wrapper that
   delegates to the class. Wrappers are deprecated with
   `warnings.warn(..., DeprecationWarning, stacklevel=2)` and removed
   in a future release.

4. **One extraction per PR.** Each step in this plan is a separate PR.
   Do not batch extractions.

5. **Characterization tests precede extraction.** Before moving code
   out of a module, write tests that exercise the behavior through the
   existing interface. These tests must pass both before AND after the
   extraction. This is how you prove the extraction preserved behavior.

---

## Callback type aliases

Several extractions introduce callback signatures. Define these in
`src/punt_lux/types.py` (new file) so both sides of each extraction
agree on the contract:

```python
"""Shared type aliases for cross-module callbacks."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

from punt_lux.protocol import InteractionMessage

EmitEventFn: TypeAlias = Callable[[InteractionMessage], None]
OnClientDisconnectedFn: TypeAlias = Callable[[int], None]
OnSceneReplacedFn: TypeAlias = Callable[[list[str]], None]
```

Create this file in Pre-flight and import from it in each extraction.

---

## Pre-flight

### P.1: Fix `_emit_event` recursion bug

**Problem.** `DisplayServer._emit_event` (line 2024) calls itself
recursively instead of appending to the event queue:

```python
def _emit_event(self, event: InteractionMessage) -> None:
    """Stamp scene_id and append to the event queue."""
    if event.scene_id is None:
        event.scene_id = self._current_scene_id
    self._emit_event(event)  # BUG: infinite recursion
```

Every `_render_*` method that emits events depends on this. The bug
is latent because `_current_scene_id` is always set before rendering,
so the `if` branch is never taken -- but any scene with
`scene_id=None` on an event would stack-overflow.

**Fix.** Replace the recursive call with the queue append:

```python
def _emit_event(self, event: InteractionMessage) -> None:
    """Stamp scene_id and append to the event queue."""
    if event.scene_id is None:
        event.scene_id = self._current_scene_id
    self._event_queue.append(event)
```

**Files modified:** `src/punt_lux/display.py` (1 line).

**Test:** Add a unit test in `tests/test_display_state.py` that
creates a server, sets `_current_scene_id`, calls `_emit_event` with
an event whose `scene_id` is `None`, and asserts the event lands in
`_event_queue` with the stamped `scene_id`. This test would
stack-overflow before the fix.

**Verification:** `make check`.

### P.2: Create `src/punt_lux/types.py`

Create the callback type alias file described above.

**Files created:** `src/punt_lux/types.py`.

**Verification:** `make check`.

### P.3: Establish baseline metrics

Run `make metrics` and record the baseline ABC scores. Run
`make coverage` and record the baseline coverage. These numbers are
compared after each phase to verify complexity decreased.

Record the results in `.tmp/refactoring-baseline.txt` (gitignored).

---

## Phase 1: `protocol.py` to `protocol/` package (3 steps)

`protocol.py` is 1,886 lines. Every other module imports from it.
Splitting it into a package with re-exports in `__init__.py` is the
safest first move: no behavior changes, only file reorganization.

### Step 1.1: Create `protocol/` package with `__init__.py` re-exports

**What to do.**

1. Create `src/punt_lux/protocol/` directory.
2. Move `src/punt_lux/protocol.py` to `src/punt_lux/protocol/__init__.py`.
3. Verify every import in the codebase (`from punt_lux.protocol import ...`)
   still resolves.

**Files created:** `src/punt_lux/protocol/__init__.py` (moved from
`src/punt_lux/protocol.py`).

**Files removed:** `src/punt_lux/protocol.py`.

**Characterization tests.** None needed -- this is a file move with
no behavior change. The existing `tests/test_protocol.py` (and every
other test that imports from `punt_lux.protocol`) is the verification.

**Verification:** `make check`. Every import resolves. All tests pass.

### Step 1.2: Extract element dataclasses to `protocol/elements.py`

**What to do.**

1. Create `src/punt_lux/protocol/elements.py`.
2. Move all 24 element dataclasses (`TextElement`, `ButtonElement`,
   `ImageElement`, `SeparatorElement`, `SliderElement`,
   `CheckboxElement`, `ComboElement`, `InputTextElement`,
   `InputNumberElement`, `RadioElement`, `ColorPickerElement`,
   `GroupElement`, `PagedGroupElement`, `TabBarElement`,
   `CollapsingHeaderElement`, `WindowElement`, `SelectableElement`,
   `TreeElement`, `TreeNodeElement`, `TableElement`, `PlotElement`,
   `ProgressElement`, `SpinnerElement`, `MarkdownElement`,
   `ModalElement`, `DrawElement`) plus the `Element` union type alias.
3. Move associated types: `TableFilter`, `TableDetail`, `Patch`,
   `TableColumn`.
4. Move the serialization functions: all `_*_to_dict` and
   `_*_from_dict` functions for elements, plus `element_to_dict`,
   `element_from_dict`, `_ELEMENT_SERIALIZERS`,
   `_ELEMENT_DESERIALIZERS`, `_strip_none`, and helper functions
   (`_color_fields_to_dict`, etc.).
5. Update `protocol/__init__.py` to re-export everything from
   `elements.py`.

**Files created:** `src/punt_lux/protocol/elements.py`.

**Files modified:** `src/punt_lux/protocol/__init__.py` (imports added,
element code removed).

**Backward compat:** `protocol/__init__.py` re-exports all names.
External imports unchanged.

**Verification:** `make check`. `tests/test_protocol.py` passes
unchanged.

### Step 1.3: Extract message dataclasses to `protocol/messages.py`

**What to do.**

1. Create `src/punt_lux/protocol/messages.py`.
2. Move all message dataclasses: `SceneMessage`, `UpdateMessage`,
   `ClearMessage`, `PingMessage`, `PongMessage`, `AckMessage`,
   `ReadyMessage`, `ConnectMessage`, `MenuMessage`,
   `RegisterMenuMessage`, `ThemeMessage`, `InteractionMessage`,
   `IntrospectRequest`, `IntrospectResponse`, `ListScenesRequest`,
   `ListScenesResponse`, `ScreenshotRequest`, `ScreenshotResponse`,
   `QueryRequest`, `QueryResponse`, `UnknownMessage`, and the
   `Message` union type alias.
3. Move serialization: `message_to_dict`, `message_from_dict`,
   `_register_serializers`, `_MESSAGE_SERIALIZERS`,
   `_MESSAGE_CODECS`, and all `_*_to_dict` / `_*_from_dict` functions
   for messages.
4. Move wire-level functions: `encode_message`, `encode_frame`.
5. `FrameReader` stays in `protocol/__init__.py` (or moves to
   `protocol/framing.py` -- implementer's choice; either way
   re-exported from `__init__`).
6. Update `protocol/__init__.py` to re-export everything from
   `messages.py`.

**Files created:** `src/punt_lux/protocol/messages.py` (and optionally
`src/punt_lux/protocol/framing.py`).

**Files modified:** `src/punt_lux/protocol/__init__.py`.

**Backward compat:** `protocol/__init__.py` re-exports all names.

**Verification:** `make check`.

**ABC metric check:** `make metrics` -- `protocol` module's aggregate
score should be approximately the same (code moved, not changed). The
value is that each sub-module is now under 800 lines.

---

## Phase 2: `display.py` extractions (6 steps)

The core of the refactoring. DisplayServer shrinks from 3,300 lines /
135 methods to ~600 lines / ~25 methods. Extraction order:
pure state machines first, then socket I/O, then table logic, then
query dispatch, then the ImGui-coupled components.

### Step 2.1: Extract `SceneManager`

**Priority:** 1 (highest testability gain, pure state machine, no
ImGui dependency).

**New file:** `src/punt_lux/scene_manager.py` (~300 LOC).

**Class:** `SceneManager` + `Frame` (promoted from `_Frame`).

**State that moves from `DisplayServer.__init__`:**

- `_scenes: dict[str, SceneMessage]`
- `_scene_order: list[str]`
- `_active_tab: str | None`
- `_frames: dict[str, Frame]`
- `_focus_frame_id: str | None`
- `_scene_to_frame: dict[str, str]`
- `_scene_to_owner: dict[str, int]`
- `_scene_widget_state: dict[str, WidgetState]`
- `_dirty_windows: set[str]`

**Methods that move from `DisplayServer`:**

- `_handle_scene` -> `SceneManager.handle_scene`
- `_handle_framed_scene` -> `SceneManager.handle_framed_scene`
- `_upsert_scene_in_frame` -> `SceneManager.upsert_scene_in_frame`
- `_replace_scene_state` -> `SceneManager.replace_scene_state`
- `_resolve_scene` -> `SceneManager.resolve_scene`
- `_apply_update` -> `SceneManager.apply_update`
- `_apply_patch_set` -> `SceneManager.apply_patch_set`
- `_dismiss_scene` -> `SceneManager.dismiss_scene`
- `_dismiss_framed_scene` -> `SceneManager.dismiss_framed_scene`
- `_close_frame` -> `SceneManager.close_frame`
- `_next_cascade_index` -> `SceneManager._next_cascade_index`

**Tree-walking utilities that move:**

- `_collect_ids` (module-level function)
- `_find_element` (module-level function)
- `_get_children` (module-level function)

These are scene-graph utilities. They belong with SceneManager.

**`_Frame` becomes `Frame`.**  The underscore prefix signals
module-private, which is wrong once the class is the primary domain
object in `scene_manager.py`.

**Constructor dependencies:**

- `emit_event: EmitEventFn` -- callback for events emitted during
  `_apply_patch_set` (e.g., tree node toggle events).
- `on_scene_replaced: OnSceneReplacedFn` -- called by
  `replace_scene_state` so DisplayServer can drain stale events from
  its own queue. SceneManager does NOT own the event queue.

**What stays on DisplayServer:**

- `_event_queue` -- the coordinator owns event dispatch.
- `_widget_state` -- the per-frame swap (`self._widget_state =
  self._scene_manager.current_widget_state(scene_id)`) stays on
  DisplayServer. SceneManager provides the lookup.
- `_test_auto_click` / `_auto_click_buttons` -- test helper, stays on
  DisplayServer.

**Characterization tests to write first** (in
`tests/test_scene_manager.py`):

1. `test_handle_scene_new` -- send a SceneMessage, verify it appears
   in `_scenes`, `_scene_order`, `_active_tab`, and that a WidgetState
   is created.
2. `test_handle_scene_replace` -- send two SceneMessages with the same
   id, verify the second replaces the first and widget state is cleared.
3. `test_handle_framed_scene` -- send a SceneMessage with `frame_id`,
   verify a Frame is created with the scene inside it.
4. `test_dismiss_scene` -- add a scene, dismiss it, verify all state
   is cleaned up and `_active_tab` selects the neighbor.
5. `test_close_frame` -- add a framed scene, close the frame, verify
   all frame and scene state is cleaned up.
6. `test_apply_update` -- add a scene, send an UpdateMessage with
   patches, verify elements are modified in-place.
7. `test_upsert_scene_dedup` -- send the same scene to two frames,
   verify it moves from the first to the second.
8. `test_clear_all` -- add scenes and frames, call `clear_all`,
   verify everything is empty.

Write these tests against the *current* `DisplayServer` first. They
must pass. Then extract `SceneManager` and update the tests to
instantiate `SceneManager` directly. They must still pass.

**Files modified after extraction:**

- `src/punt_lux/display.py` -- DisplayServer delegates to
  `self._scene_manager`. Thin wrapper methods for backward compat
  where needed internally.
- `src/punt_lux/scene_manager.py` -- new file.

**Verification:** `make check`. `make metrics` -- `display.py`
ABC score decreases.

### Step 2.2: Extract `SocketServer`

**Priority:** 2 (no ImGui dependency, high testability).

**New file:** `src/punt_lux/socket_server.py` (~200 LOC).

**Class:** `SocketServer`.

**Methods that move from `DisplayServer`:**

- `_setup_socket` -> `SocketServer.setup`
- `_accept_connections` -> `SocketServer.accept_connections`
- `_poll_clients` -> `SocketServer.poll_clients`
- `_read_from_client` -> `SocketServer._read_from_client`
- `_remove_client` -> `SocketServer.remove_client`
- `_send_to_client` -> `SocketServer.send_to_client`

**State that moves:**

- `_server_sock: socket.socket | None`
- `_clients: list[socket.socket]`
- `_readers: dict[int, FrameReader]`
- `_fd_to_client: dict[int, socket.socket]`
- `_client_names: dict[int, str]`
- `_client_connect_times: dict[int, float]`

**Constructor dependencies:**

- `on_message: Callable[[socket.socket, Message], None]` -- callback
  for each deserialized message. DisplayServer's `_handle_message`
  is registered here.
- `on_client_disconnected: OnClientDisconnectedFn` -- callback when a
  client fd disconnects. DisplayServer uses this to transfer scene
  ownership.
- `on_error: Callable[[str, str, str], None]` -- callback for error
  recording (currently `_record_error`).

**Characterization tests to write first** (in
`tests/test_socket_server.py`):

1. `test_setup_creates_socket` -- call `setup`, verify the socket file
   exists and `_server_sock` is not None.
2. `test_accept_and_poll` -- set up a server socket, connect a client,
   call `accept_connections`, verify the client appears in `_clients`.
   Send a message from the client, call `poll_clients`, verify the
   `on_message` callback fires.
3. `test_remove_client_cleanup` -- connect a client, remove it, verify
   all per-client state is cleaned up.
4. `test_buffer_overflow_disconnect` -- send more than
   `MAX_MESSAGE_SIZE` bytes, verify the client is disconnected.

**Files modified:**

- `src/punt_lux/display.py` -- DisplayServer creates `self._socket_server`
  in `_on_post_init` and delegates.
- `src/punt_lux/socket_server.py` -- new file.

**Verification:** `make check`. `make metrics`.

### Step 2.3: Extract `TableRenderer`

**Priority:** 3 (module-level functions become a class, filter logic
is pure Python and highly testable).

**New file:** `src/punt_lux/table_renderer.py` (~500 LOC).

**Class:** `TableRenderer`.

**Functions that move from module-level in `display.py`:**

- `_render_filter_search`
- `_render_filter_combo`
- `_get_filter_snapshot`
- `_apply_table_filters`
- `_filter_indexed_rows`
- `_filter_combo`
- `_render_table_pagination`
- `_maybe_copy_id`
- `_parse_table_flags`
- `_render_table_rows`
- `_handle_table_keyboard_nav`
- `_render_table_detail`
- `_render_detail_field_grid`
- `_table_column_weights`
- `IndexedRow` type alias
- `_ROWS_PER_PAGE` constant

**Also moves from `DisplayServer`:**

- `_render_table` method -- becomes `TableRenderer.render`. The
  `_RENDERERS` dict entry for `"table"` delegates to the
  `TableRenderer` instance.

**Constructor dependencies:**

- `emit_event: EmitEventFn` -- for table row selection events.

**Why a class.** The 15 module-level functions all take the same
parameters: `widget_state`, `table_id`, `imgui`. This is a class
spelled as free functions. The constructor takes `widget_state` and
`imgui`; `table_id` is a method parameter. The filter logic
(`_apply_table_filters`, `_filter_indexed_rows`, `_filter_combo`) is
pure Python and can be tested without ImGui.

**Characterization tests to write first** (in
`tests/test_table_renderer.py`):

1. `test_apply_table_filters_search` -- create rows and a search
   filter, verify correct rows are returned.
2. `test_apply_table_filters_combo` -- create rows and a combo filter,
   verify correct rows are returned.
3. `test_filter_indexed_rows` -- verify the indexing is preserved
   through filtering.
4. `test_column_weights` -- verify column width calculation.
5. `test_filter_snapshot_change_detection` -- verify the snapshot
   string changes when filter state changes.

These test the pure filter logic and do not require ImGui.

**Backward compat:** The module-level functions stay in `display.py`
as thin wrappers that delegate to a module-level `TableRenderer`
instance. This preserves any internal callers.

**Files modified:**

- `src/punt_lux/display.py` -- module-level functions become wrappers.
  `DisplayServer._render_table` delegates to `self._table_renderer`.
- `src/punt_lux/table_renderer.py` -- new file.

**Verification:** `make check`. `make metrics` -- `display.py` ABC
score decreases.

### Step 2.4: Extract `QueryDispatcher`

**Priority:** 4 (pure dispatch, no ImGui dependency, fully
unit-testable).

**New file:** `src/punt_lux/query_dispatcher.py` (~300 LOC).

**Class:** `QueryDispatcher`.

**Methods that move from `DisplayServer`:**

- `_handle_query` -> `QueryDispatcher.handle_query`
- `_query_inspect_scene`
- `_query_list_scenes`
- `_query_screenshot`
- `_query_list_recent_events`
- `_query_list_errors`
- `_record_error` -> `QueryDispatcher.record_error`

**Handler implementations that stay on DisplayServer** (because they
need display-wide state):

- `_query_get_display_info` -- needs `_start_time`, `_themes`, window
  dimensions, ImGui backend info.
- `_query_get_window_settings` -- needs `_decorated`, `_opacity`,
  `_font_scale`.
- `_query_get_theme` -- needs `_current_theme`, `_themes`.
- `_query_set_window_settings` -- mutates display-wide state.
- `_query_set_frame_state` -- needs ImGui window state.
- `_query_set_theme` -- calls `_apply_theme`.

These stay on DisplayServer and are registered as `Callable` handlers
during QueryDispatcher construction.

**Handler implementations that move WITH `QueryDispatcher`:**

- `_query_list_clients` -- needs only `_client_names`,
  `_client_connect_times`, and `_scene_to_owner`. These are passed as
  read accessors (lambdas or references to SceneManager/SocketServer).
- `_query_list_menus` -- needs `_menu_registrations`, `_agent_menus`.
  Passed as read accessors.

**State that moves:**

- `_query_handlers: dict[str, Callable[..., dict[str, Any]]]`
- `_recent_events: deque[dict[str, Any]]` (ring buffer)
- `_recent_errors: deque[dict[str, Any]]` (ring buffer)

**Constructor dependencies:**

- `scene_manager: SceneManager` -- for `inspect_scene`, `list_scenes`.
- Read accessors for client and menu state (lambdas or protocol
  objects, not references to DisplayServer).

**Characterization tests to write first** (in
`tests/test_query_dispatcher.py`):

1. `test_dispatch_known_method` -- register a handler, send a
   QueryRequest, verify the handler is called and response is correct.
2. `test_dispatch_unknown_method` -- send a QueryRequest with an
   unregistered method, verify error response.
3. `test_record_event_ring_buffer` -- record 250 events (buffer size
   200), verify only the last 200 are retained.
4. `test_record_error_ring_buffer` -- same for errors (buffer size
   100).
5. `test_list_recent_events` -- record events, query them, verify
   count limiting works.

**Files modified:**

- `src/punt_lux/display.py` -- DisplayServer creates
  `self._query_dispatcher` and registers its own handlers.
- `src/punt_lux/query_dispatcher.py` -- new file.

**Verification:** `make check`. `make metrics`.

### Step 2.5: Extract `ElementRenderer`

**Priority:** 5 (largest extraction by LOC, needs ImGui).

**New file:** `src/punt_lux/element_renderer.py` (~1,200 LOC).

**Class:** `ElementRenderer`.

**Design pattern:** Visitor. The `_RENDERERS` dict maps element kind
strings to method names. When a new element kind is added, one method
is added to `ElementRenderer` and one entry to `_RENDERERS`. This is
the Open/Closed Principle: the class is open for extension (new
element kinds) and closed for modification (existing render methods
don't change).

**Methods that move from `DisplayServer`:**

- `_render_element` -> `ElementRenderer.render_element`
- All 24 `_render_*` methods (text, button, separator, image, slider,
  checkbox, combo, input_text, input_number, radio, color_picker,
  group, paged_group, tab_bar, collapsing_header, window, selectable,
  tree, tree_node, table, plot, progress, spinner, markdown, modal,
  draw).
- `_render_text_tooltip`
- `_parse_hex_color`
- `_resolve_arrow_dir` (if present)
- `_RENDERERS` class variable

**Color helpers that move:**

- `_parse_color` (module-level)
- `_color_to_hex` (module-level, if present)
- `_to_imgui_color` (module-level, if present)
- `_widget_value` (module-level, if present)

These are rendering utilities that belong with the renderer.

**Constructor dependencies (three):**

- `widget_state: WidgetState` -- mutable reference, swapped by
  DisplayServer before each scene render.
- `texture_cache: TextureCache` -- for `_render_image`.
- `emit_event: EmitEventFn` -- for user interaction events.

**Widget state handoff.** DisplayServer sets
`element_renderer.widget_state = scene_manager.current_widget_state(scene_id)`
before each scene render. This is an explicit assignment, not a shared
mutable reference threaded through layers.

**Note on `_render_table`.** If Step 2.3 has already extracted
`TableRenderer`, then `ElementRenderer._render_table` delegates to
`self._table_renderer`. If not, `_render_table` moves wholesale and
`TableRenderer` extraction happens later as a sub-extraction.

**Characterization tests.** ElementRenderer requires ImGui. The
existing tests in `test_display_state.py` that exercise event emission
from render methods are the characterization tests. No new pure-logic
tests are possible here. Verification is that the existing test suite
passes after extraction.

**Files modified:**

- `src/punt_lux/display.py` -- DisplayServer creates
  `self._element_renderer` and delegates `_render_element`.
- `src/punt_lux/element_renderer.py` -- new file.

**Verification:** `make check`. `make metrics` -- `display.py` ABC
score drops substantially (~1,200 lines removed).

### Step 2.6: Extract `MenuManager`

**Priority:** 6 (ImGui rendering, depends on ElementRenderer for
event emission pattern).

**New file:** `src/punt_lux/menu_manager.py` (~400 LOC).

**Class:** `MenuManager`.

**Methods that move from `DisplayServer`:**

- `_show_menus` -> `MenuManager.show_menus`
- `_show_lux_menu`, `_show_lux_items`
- `_show_apps_menu`
- `_show_window_menu`, `_show_window_frame_items`,
  `_show_window_chrome_items`
- `_show_help_menu`, `_show_help_items`
- `_show_agent_menu`
- `_check_world_menu_background_click`
- `_render_world_panel`, `_render_world_panel_sections`,
  `_render_world_panel_apps`
- `_handle_register_menu`, `_sanitize_menu_items`
- `_sorted_app_clients` (if present), `_render_registered_item`,
  `_display_name` (if present)

**State that moves:**

- `_agent_menus: list[dict[str, Any]]`
- `_menu_registrations: dict[int, list[dict[str, Any]]]`
- `_menu_owners: dict[str, int]`
- `_world_menu_open: bool`
- `_world_menu_pinned: bool`
- `_world_menu_spawn_pos: tuple[float, float] | None`

**State that stays on DisplayServer** (not menu state):

- `_themes`, `_current_theme` -- display-wide theme state.
- `_decorated`, `_opacity`, `_font_scale` -- window chrome state.

MenuManager receives callbacks for user selections (e.g., "user
selected theme X", "user toggled decorated") but does not own the
state those callbacks mutate.

**Constructor dependencies:**

- `emit_event: EmitEventFn` -- for menu click events.
- `on_theme_selected: Callable[[str], None]`
- `on_decorated_toggled: Callable[[bool], None]`
- `on_opacity_changed: Callable[[float], None]`
- `on_font_scale_changed: Callable[[float], None]`
- Read accessors for theme list, current theme, decorated state, etc.

**Characterization tests.** MenuManager requires ImGui. The existing
tests in `test_display_state.py` that test menu registration and
sanitization are the characterization tests. Write additional tests for
`_sanitize_menu_items` (pure logic) before extraction:

1. `test_sanitize_rejects_duplicate_owner` -- verify that registering
   an item ID already owned by a different fd returns None.
2. `test_sanitize_deduplicates` -- verify that duplicate item IDs
   within a single registration are collapsed.
3. `test_handle_register_menu_updates_owners` -- verify that item
   ownership is tracked correctly.

**Files modified:**

- `src/punt_lux/display.py` -- DisplayServer creates
  `self._menu_manager` and delegates.
- `src/punt_lux/menu_manager.py` -- new file.

**Verification:** `make check`. `make metrics`.

### Phase 2 verification gate

After all six extractions, DisplayServer should be ~600 lines with
~25 methods. Run `make metrics` and verify:

- `display.py` ABC magnitude < 400 (down from ~1,795).
- No new module exceeds ABC magnitude 500.
- `make coverage` shows the new modules have comparable coverage to
  the old monolith.

---

## Phase 3: `tools.py` refactor (2 steps)

### Step 3.1: Add `_query_tool` decorator, migrate 15 query tools

**What to do.**

Add a `_query_tool` decorator to `tools.py` that eliminates the
repeated 12-line pattern across 15 query-wrapper tools:

```python
def _query_tool(
    method: str,
    *,
    doc: str = "",
) -> Callable[..., Callable[..., str]]:
    def decorator(fn: Callable[..., dict[str, Any] | None]) -> Callable[..., str]:
        @mcp.tool()
        @functools.wraps(fn)
        def wrapper(**kwargs: Any) -> str:
            if not is_display_running(default_socket_path()):
                return "not running"
            params = fn(**kwargs) or {}

            def _call() -> str:
                client = _get_client()
                response = client.query(method, params)
                if response is None:
                    return "timeout"
                if response.error:
                    return f"error: {response.error}"
                return json.dumps(response.result, indent=2)

            return _with_reconnect(_call)

        if doc:
            wrapper.__doc__ = doc
        return wrapper

    return decorator
```

**Tools to migrate** (each becomes 3-10 lines):

1. `get_display_info`
2. `get_window_settings`
3. `get_theme`
4. `list_clients`
5. `list_menus`
6. `list_recent_events`
7. `list_errors`
8. `inspect_scene`
9. `list_scenes`
10. `screenshot`
11. `set_theme`
12. `set_window_settings`
13. `set_frame_state`
14. `ping` (if it follows the pattern)
15. `clear` (if it follows the pattern)

**FastMCP compatibility check.** After migrating one tool, call
`mcp.list_tools()` and verify the schema is correct. If the decorated
function's return type annotation (`dict | None`) confuses FastMCP,
override `wrapper.__annotations__["return"]` to `str`.

**Characterization tests.** The existing `tests/test_tools.py` is the
characterization test. Verify it passes after each tool migration.

**Files modified:** `src/punt_lux/tools.py` (~150 lines of boilerplate
removed).

**Verification:** `make check`.

### Step 3.2: Add `ToolState` class (optional)

**What to do.** Extract the 5 module-level variables into a `ToolState`
class:

- `_client: DisplayClient | None`
- `_client_lock: threading.RLock`
- `_session_key: ContextVar[str]`
- `_session_menus: dict[str, list[str]]`
- `_apps_registered_for: int | None`

**ContextVar subtlety.** `ContextVar` is tied to asyncio task context.
It must remain at module scope or be accessed via the class as a class
variable, not stored as instance state. The `ToolState` class should
hold a reference to the module-level `ContextVar`, not create a new
one.

**This step is optional.** The module-level state works. The gain is
testability: a `ToolState` instance can be injected with a mock
`DisplayClient`. Defer if testing `tools.py` is not a near-term goal.

**Files modified:** `src/punt_lux/tools.py`.

**Verification:** `make check`.

---

## Phase 4: `display_client.py` migration (2 steps)

Independent of the `display.py` decomposition. Can run in parallel
with Phase 2.

### Step 4.1: Deprecate `inspect_scene`, `list_scenes`, `screenshot`

**What to do.** The three methods become thin wrappers around
`query()`:

```python
def inspect_scene(self, scene_id: str) -> IntrospectResponse | None:
    """Deprecated: use query('inspect_scene', {'scene_id': scene_id})."""
    warnings.warn(
        "inspect_scene() is deprecated, use query('inspect_scene', ...)",
        DeprecationWarning,
        stacklevel=2,
    )
    resp = self.query("inspect_scene", {"scene_id": scene_id})
    if resp is None:
        return None
    # Adapt QueryResponse to IntrospectResponse for backward compat
    return IntrospectResponse(
        scene_id=scene_id,
        elements=resp.result.get("elements", []),
    )
```

Same pattern for `list_scenes` and `screenshot`.

**Characterization tests.** The existing `tests/test_display_client.py`
covers these methods. Verify all tests pass after migration.

**Files modified:** `src/punt_lux/display_client.py`.

**Verification:** `make check`.

### Step 4.2: Remove deprecated methods and 3 queues

**What to do.** In a subsequent release (after deprecation period):

1. Remove `inspect_scene`, `list_scenes`, `screenshot` methods.
2. Remove `_introspect_queue`, `_list_scenes_queue`,
   `_screenshot_queue`.
3. Simplify `_dispatch_or_buffer` (remove 3 `isinstance` checks).
4. Simplify `close()` (remove 3 `_drain_queue` calls).

**Files modified:** `src/punt_lux/display_client.py` (~100 lines
removed, 3 queues eliminated).

**Verification:** `make check`.

---

## Phase 5: Smaller module refactors (7 steps)

These are independent of each other and can be done in any order.

### Step 5.1: `service.py` -- `ServiceManager` + platform backends

**Design pattern:** Strategy (Open/Closed Principle). The parallel
function sets (`_launchd_install` / `_systemd_install`, etc.) become
polymorphic classes. Adding a third platform is a single new class,
not a modification to existing `install()` / `uninstall()`.

**New classes:**

- `ServiceBackend` (ABC): `install`, `uninstall`, `is_active`,
  `config_path`.
- `LaunchdBackend(ServiceBackend)`: moves `_launchd_plist_content`,
  `_launchd_install`, `_launchd_uninstall`, `_launchd_status`.
- `SystemdBackend(ServiceBackend)`: moves `_systemd_unit_content`,
  `_systemd_install`, `_systemd_uninstall`, `_systemd_status`,
  `_systemd_escape`.
- `ServiceManager`: `_resolve_backend`, `install`, `uninstall`,
  `restart` (moved from `__main__.py._restart_hub`).

**Shared helpers that stay module-level:**

- `_luxd_exec_args` -- binary resolution, not platform-specific.
- `detect_platform` -- returns platform string, used by
  `_resolve_backend`.
- `_has_linger` -- Linux-specific, moves to `SystemdBackend`.

**Backward compat:**

```python
_manager = ServiceManager()

def install() -> str:
    return _manager.install()

def uninstall() -> str:
    return _manager.uninstall()
```

**Characterization tests** (in `tests/test_service.py`):

1. `test_launchd_plist_content` -- verify the plist XML is valid.
2. `test_systemd_unit_content` -- verify the unit file is valid.
3. `test_detect_platform` -- verify correct platform detection.
4. `test_mock_backend_install` -- create a `MockBackend`, verify
   `ServiceManager` delegates correctly.

**Files modified:** `src/punt_lux/service.py`.

**Verification:** `make check`.

### Step 5.2: `hub.py` -- `SessionHub` class

**What to do.** Encapsulate `_active_sessions: set[str]` and the
Starlette app factory into `SessionHub`.

**Methods that move:**

- `_health_route` -> `SessionHub._health_route`
- `_mcp_websocket_route` -> `SessionHub._mcp_websocket_route`
- `build_app` -> `SessionHub._build_app` (called in constructor)

**What stays module-level:**

- `serve` function (creates a SessionHub and runs uvicorn).
- `main` entry point.
- `_write_port_file`, `_remove_port_file` -- file I/O helpers.

**Characterization tests** (in `tests/test_hub.py`):

1. `test_health_route` -- use Starlette TestClient, verify JSON
   response includes `sessions` count.
2. `test_session_tracking` -- verify `_active_sessions` is updated
   on WebSocket connect/disconnect.

**Files modified:** `src/punt_lux/hub.py`.

**Verification:** `make check`.

### Step 5.3: `__main__.py` -- extract `DoctorChecker`, hub sub-app

**Two sub-steps:**

**5.3a: Extract `DoctorChecker` to `src/punt_lux/doctor.py`.**

New class with methods: `check_python_version`, `check_imgui_bundle`,
`check_fonts`, `check_display_server`, `check_plugin`, `run_all`,
`print_report`. Properties: `results`, `passed`, `failed`.

Move from `__main__.py`:

- `_check_fonts` function
- `_check_plugin` function (if present)
- `_CheckFn` protocol type (eliminated -- the checker owns result
  accumulation)
- Doctor command body (100 lines -> 7 lines)
- `_OK`, `_FAIL`, `_OPTIONAL` constants
- `_PLUGIN_ID` constant

`CheckResult` dataclass: `symbol`, `message`, `required`.

**5.3b: Create hub Typer sub-app.**

```python
hub_app = typer.Typer(help="Hub daemon management.")
app.add_typer(hub_app, name="hub")
```

Move: `hub-install` -> `hub install`, `hub-uninstall` -> `hub uninstall`,
`hub-status` -> `hub status`, `ensure-hub` -> `hub ensure`,
`setup-proxy` -> `hub setup-proxy`.

**CLI change:** `lux hub-install` becomes `lux hub install`. This is a
breaking CLI change. Add backward-compat aliases if needed:

```python
# Backward compat: old hyphenated commands
@app.command("hub-install", hidden=True)
def hub_install_compat() -> None:
    hub_install()
```

**5.3c: Move `_restart_hub` to `service.py`.**

The 50-line function that sends SIGTERM and waits for respawn is daemon
lifecycle management. It becomes `ServiceManager.restart()`.

**Characterization tests:**

1. `test_doctor_checker_fonts` -- mock font paths, verify check
   results.
2. `test_doctor_checker_run_all` -- run all checks, verify passed/
   failed counts.

**Files created:** `src/punt_lux/doctor.py`.

**Files modified:** `src/punt_lux/__main__.py`, `src/punt_lux/service.py`.

**Verification:** `make check`.

### Step 5.4: `paths.py` -- `DisplayPaths` class

**Design pattern:** Parameter Object. The socket path is threaded
through 6 of 8 functions; making it a constructor argument eliminates
the parameter threading.

**New class:** `DisplayPaths`.

**Methods (from module-level functions):**

- `default_socket_path` -> `DisplayPaths._default_path` (static)
- `pid_file_path` -> `DisplayPaths.pid_path` (property)
- `log_file_path` -> `DisplayPaths.log_path` (property)
- `is_display_running` -> `DisplayPaths.is_running`
- `cleanup_stale_socket` -> `DisplayPaths.cleanup_stale`
- `ensure_display` -> `DisplayPaths.ensure`
- `write_pid_file` -> `DisplayPaths.write_pid`
- `remove_pid_file` -> `DisplayPaths.remove_pid`

**Hub functions stay as module-level functions:** `hub_dir`,
`hub_pid_path`, `hub_port_path`, `hub_log_dir`, `read_hub_port`,
`is_hub_running`. These are stateless pure functions derived from
constants. No class needed.

**Backward compat:**

```python
def default_socket_path() -> Path:
    return DisplayPaths().socket_path

def is_display_running(socket_path: Path) -> bool:
    return DisplayPaths(socket_path).is_running()
```

**Characterization tests:** The existing `tests/test_paths.py` is
the characterization test suite. Verify it passes unchanged.

**Files modified:** `src/punt_lux/paths.py`.

**Verification:** `make check`.

### Step 5.5: `config.py` -- `ConfigManager` class

**New class:** `ConfigManager`.

**Methods (from module-level functions):**

- `resolve_config_path` -> stays as module-level (cached, used by
  constructor default).
- `read_config` -> `ConfigManager.read`
- `read_field` -> `ConfigManager.read_field`
- `write_field` -> `ConfigManager.write_field`
- `_extract_frontmatter` -> `ConfigManager._extract_frontmatter`
  (private method or stays module-level)

`LuxConfig` stays as-is (frozen data snapshot, correct use of
dataclass).

**Backward compat:**

```python
_default_manager = ConfigManager()

def read_config(config_path: Path | None = None) -> LuxConfig:
    if config_path is not None:
        return ConfigManager(config_path).read()
    return _default_manager.read()
```

**Characterization tests:** The existing `tests/test_config.py` is
the characterization test. Verify it passes.

**Files modified:** `src/punt_lux/config.py`.

**Verification:** `make check`.

### Step 5.6: `remote.py` -- `ProxyConfigFile` class

**New class:** `ProxyConfigFile`.

**Methods (from module-level functions):**

- `read_proxy_config` -> `ProxyConfigFile.read`
- `write_proxy_config` -> `ProxyConfigFile.write`
- `delete_proxy_config` -> `ProxyConfigFile.delete`
- `_atomic_write` -> `ProxyConfigFile._atomic_write` (private)
- `_serialize_config` -> `ProxyConfigFile._serialize_config` (private
  or static)
- `_toml_escape` -> `ProxyConfigFile._toml_escape` (static)

Constructor: `path: Path | None = None`, defaults to
`MCP_PROXY_CONFIG_PATH`.

**Backward compat:**

```python
_default_proxy = ProxyConfigFile()

def read_proxy_config() -> dict[str, Any]:
    return _default_proxy.read()

def write_proxy_config(url: str) -> None:
    _default_proxy.write(url)

def delete_proxy_config() -> bool:
    return _default_proxy.delete()
```

**Characterization tests:** The existing `tests/test_remote.py` is
the characterization test. Verify it passes.

**Files modified:** `src/punt_lux/remote.py`.

**Verification:** `make check`.

### Step 5.7: `apps/beads.py` -- `BeadsBrowser` class

**New class:** `BeadsBrowser`.

**Methods (from module-level functions):**

- `load_beads` -> `BeadsBrowser.load`
- `build_beads_payload` -> `BeadsBrowser.build_payload`
- `build_beads_elements` -> `BeadsBrowser.build_elements`
- `render_beads_board` -> `BeadsBrowser.render`
- `_FIELD_DEFAULTS` -> `BeadsBrowser.FIELD_DEFAULTS` (ClassVar)

**Backward compat:**

```python
_browser = BeadsBrowser()
load_beads = _browser.load
build_beads_payload = _browser.build_payload
build_beads_elements = _browser.build_elements
render_beads_board = _browser.render
```

**Characterization tests:** The existing `tests/test_show.py` is the
characterization test (it exercises the beads pipeline). Verify it
passes.

**Files modified:** `src/punt_lux/apps/beads.py`.

**Verification:** `make check`.

---

## Modules that remain function-only

These modules have no class and the design report explains why.

### `hooks.py`

Each function is invoked in a separate OS process by the Claude Code
hook protocol. No persistent state across invocations. A
`HookDispatcher` class would encapsulate nothing. The module is the
namespace.

### `show.py`

One Typer command delegating to `beads.py` and `DisplayClient`. No
state, no shared logic. The module is the namespace.

### `__init__.py`

Package export surface. After module splits, imports are updated but
the structure is correct.

---

## `_auto_click_buttons` disposition

The 90-line test-mode method `_auto_click_buttons` stays on
DisplayServer gated by `_test_auto_click`. It is a test helper that
fires synthetic events -- it belongs with the coordinator that owns
the event queue and the test lifecycle. If it grows further, move it
to a `test_helpers.py` module.

---

## File layout after refactoring

```text
src/punt_lux/
    types.py             ~15 LOC   (callback type aliases)
    protocol/
        __init__.py      ~50 LOC   (re-exports)
        elements.py      ~900 LOC  (24 element dataclasses + ElementCodec)
        messages.py      ~800 LOC  (message dataclasses + MessageCodec)
        framing.py       ~200 LOC  (FrameReader + wire format)
    display.py           ~900 LOC  (DisplayServer: lifecycle + layout + message routing)
    socket_server.py     ~200 LOC  (SocketServer)
    scene_manager.py     ~300 LOC  (SceneManager + Frame)
    element_renderer.py  ~1200 LOC (ElementRenderer — Visitor pattern)
    table_renderer.py    ~500 LOC  (TableRenderer)
    menu_manager.py      ~400 LOC  (MenuManager)
    query_dispatcher.py  ~300 LOC  (QueryDispatcher)
    doctor.py            ~120 LOC  (DoctorChecker)
    tools.py             ~900 LOC  (query decorator reduces boilerplate)
    display_client.py    ~600 LOC  (after query migration)
    __main__.py          ~300 LOC  (thin CLI wiring, hub sub-app)
    service.py           ~350 LOC  (ServiceManager + backends)
    hub.py               ~230 LOC  (SessionHub)
    paths.py             ~170 LOC  (DisplayPaths class + hub functions)
    config.py            ~190 LOC  (ConfigManager + LuxConfig)
    remote.py            ~90 LOC   (ProxyConfigFile)
    runtime.py           ~174 LOC  (RenderContext, CodeExecutor — unchanged)
    hooks.py             ~127 LOC  (unchanged — stateless dispatchers)
    show.py              ~58 LOC   (unchanged — thin CLI wiring)
    apps/beads.py        ~230 LOC  (BeadsBrowser)
    __init__.py          ~110 LOC  (updated imports)
```

Total: ~10K LOC across ~25 files, largest module ~1,200 lines
(ElementRenderer -- justified by 24 parallel render methods that share
one responsibility).

---

## Dependency graph after refactoring

```text
DisplayServer (coordinator)
  ├── SceneManager         (pure state machine)
  ├── SocketServer         (IPC layer)
  ├── ElementRenderer      (Visitor — ImGui rendering)
  │     └── TableRenderer  (table-specific rendering)
  ├── MenuManager          (menu state + ImGui rendering)
  └── QueryDispatcher      (introspection dispatch)

All upward edges are Callable parameters, never imports.
No extracted class imports DisplayServer.
```

---

## Execution notes

1. **One PR per step.** Each step in this plan maps to one PR. Steps
   within a phase are ordered. Steps across phases can sometimes be
   parallelized (Phase 3 and Phase 4 are independent of Phase 2).

2. **Characterization tests first.** Before each extraction, write the
   specified tests against the current code. Merge the tests. Then do
   the extraction in a separate PR. This way, if the extraction
   introduces a regression, the test catches it.

3. **`make metrics` after each phase.** Record the ABC scores. The
   trend must be downward for `display.py`. If an extraction increases
   complexity anywhere, investigate before proceeding.

4. **Import linting.** After each extraction, verify the no-import
   invariant:

   ```bash
   grep -r 'from punt_lux.display import' src/punt_lux/scene_manager.py
   grep -r 'from punt_lux.display import' src/punt_lux/socket_server.py
   # etc. — must return nothing
   ```

5. **The `_emit_event` fix is pre-flight, not optional.** Every
   extracted class that emits events depends on this method working
   correctly. Fix it first.
