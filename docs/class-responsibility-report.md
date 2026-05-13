# Class Responsibility Report

Analysis of `src/punt_lux/` -- every class that exists, every class that
should exist, what each one owns, what it collaborates with, and which
existing functions/methods move into it.

Calibration: the merchants/game reference project has 2K LOC across 14
files, 20 classes, largest module 363 lines.  Each class has one
responsibility (`RoundController` manages rounds and turns, `Captain`
owns position and cargo and trades, `Deck` shuffles and draws, `Game`
is a facade that wires everything together).  Lux has 10K LOC across
17 files, 5 real classes, largest module 4,208 lines.  The ratio is
inverted: 5x more code, 4x fewer classes.

---

## Current inventory

| Module | LOC | Classes | Top-level functions |
|--------|-----|---------|---------------------|
| display.py | 4,208 | 3 (TextureCache, WidgetState, DisplayServer) | 28 |
| protocol.py | 1,886 | 32 dataclasses + FrameReader | 73 |
| tools.py | 1,089 | 0 | 29 MCP tools + 7 helpers |
| display_client.py | 692 | 1 (DisplayClient) | 1 |
| \_\_main\_\_.py | 572 | 0 | 22 CLI commands |
| service.py | 347 | 0 | 14 |
| apps/beads.py | 228 | 0 | 5 |
| hub.py | 224 | 0 | 8 |
| config.py | 186 | 1 (LuxConfig) | 5 |
| runtime.py | 174 | 2 (RenderContext, CodeExecutor) | 0 |
| paths.py | 172 | 0 | 13 |
| hooks.py | 127 | 0 | 4 |
| remote.py | 85 | 0 | 5 |
| show.py | 58 | 0 | 1 CLI command + re-exports |
| \_\_init\_\_.py | 107 | 0 | package exports |

---

## display.py decomposition

`DisplayServer` is 3,300 lines with 135 methods.  It handles at least
eight distinct responsibilities.  The module-level functions add another
900 lines of table/filter rendering logic that implicitly belongs to a
table renderer class.

### TextureCache

- **Status**: EXISTS
- **Module**: `punt_lux.display`
- **Responsibility**: Map image file paths to OpenGL texture IDs, uploading on first access.
- **Compositions**: None
- **Collaborations**:
  - DisplayServer.\_render\_image -- sole consumer
  - OpenGL.GL -- uploads textures
  - PIL.Image -- loads image files
- **Key methods**: `get_or_load(path: str) -> int | None`, `cleanup() -> None`
- **Notes**: Well-scoped.  No changes needed.  Moves to its own module
  when display.py is split, but the class itself is fine.

### WidgetState

- **Status**: EXISTS
- **Module**: `punt_lux.display`
- **Responsibility**: Key-value store for interactive widget values that persist across ImGui frames.
- **Compositions**: None
- **Collaborations**:
  - DisplayServer -- owns one per scene, swaps on tab switch
  - Every `_render_*` method reads/writes via `self._widget_state`
  - Table filter functions -- receive WidgetState as parameter
- **Key methods**: `get(element_id, default)`, `set(element_id, value)`, `ensure(element_id, default)`, `clear()`, `clear_suffix(suffix)`
- **Notes**: Well-scoped.  Should move to its own module or to
  protocol.py when display.py is split.

### DisplayServer (residual after extractions)

- **Status**: NEEDS REFACTOR
- **Module**: `punt_lux.display`
- **Responsibility**: Currently eight responsibilities in one class. After extraction, the ImGui render loop coordinator -- lifecycle, frame dispatch, message routing, and the `_on_frame` / `_on_exit` callbacks.
- **What it should be**: ~600 lines. The render loop lifecycle (`run`, `_on_post_init`, `_on_frame`, `_on_after_swap`, `_on_exit`), font loading, screenshot capture, idle flame rendering, frame window layout (`_render_frames`, `_render_single_frame`, `_render_dock_bar`, `_apply_fit_all`, `_compute_tile_layout`), and the message dispatcher (a method, not a class).
- **Compositions**:
  - SocketServer -- IPC layer
  - SceneManager -- scene graph state machine
  - ElementRenderer -- ImGui element rendering
  - MenuManager -- menu state and rendering
  - QueryDispatcher -- introspection/control queries
- **Collaborations**:
  - imgui_bundle -- render loop integration
  - glfw -- window management
- **Notes**: DisplayServer creates all extracted managers in `_on_post_init` and passes them to each other via constructor injection. Managers never import DisplayServer. Upward communication uses callbacks (Callable), not bidirectional imports.

  Theme state (`_themes`, `_current_theme`, `_apply_theme`) and window
  chrome state (`_decorated`, `_opacity`, `_font_scale`) stay on
  DisplayServer -- they are display-wide, not menu-specific.
  MenuManager receives callbacks for user selections, not ownership
  of these fields.

**Responsibilities to extract:**

1. **Socket I/O** (accept, poll, read, send, remove\_client) -- 7 methods, ~180 lines
2. **Scene/frame management** (handle\_scene, upsert, dismiss, resolve, apply\_update) -- 12 methods, ~250 lines
3. **Menu system** (show\_menus, show\_lux\_menu, show\_apps\_menu, show\_window\_menu, show\_help\_menu, world panel, registered items) -- 18 methods, ~350 lines (theme/chrome excluded)
4. **Element renderers** (24 \_render\_\* methods) -- ~1,200 lines
5. **Introspection/query handlers** (13 \_query\_\* methods + \_handle\_query) -- ~250 lines
6. **Table rendering** (module-level: filters, pagination, detail, column weights) -- ~450 lines in 15 functions

---

### Frame

- **Status**: EXISTS (as `_Frame`, line 851) -- NEEDS PROMOTION
- **Module**: `punt_lux.scene_manager` (new, moves from `punt_lux.display`)
- **Responsibility**: State for a named inner window -- owns scenes, tracks layout mode, cascade index, minimized state.
- **Compositions**: Scene list, layout metadata
- **Collaborations**: SceneManager -- managed by SceneManager
- **Key methods**: Current dataclass fields.
- **Notes**: Rename from `_Frame` to `Frame`.  The underscore prefix
  signals "private to this module" which is no longer accurate when
  it lives in `scene_manager.py`.  This is a first-class domain
  object, not a private implementation detail.  SceneManager's
  primary job is managing Frame instances.

### SocketServer

- **Status**: PROPOSED
- **Module**: `punt_lux.socket_server` (new)
- **Responsibility**: Accept, poll, read from, send to, and remove Unix socket client connections.
- **Compositions**:
  - FrameReader (one per client fd) -- buffered message framing
- **Collaborations**:
  - DisplayServer -- calls `poll()` each frame, receives typed messages
  - protocol.encode\_message / FrameReader.drain\_typed -- wire format
- **Key methods**:
  - `setup(socket_path: Path) -> None`
  - `accept_connections() -> None`
  - `poll_clients() -> list[tuple[int, Message]]`
  - `send_to_client(fd: int, msg: Message) -> None`
  - `remove_client(fd: int) -> None`
  - `broadcast(msg: Message) -> None`
- **Related functions (to move from DisplayServer)**:
  - `_setup_socket`
  - `_accept_connections`
  - `_poll_clients`
  - `_read_from_client`
  - `_remove_client`
  - `_send_to_client`
- **Notes**: The socket layer has no ImGui dependency.  Extracting it
  makes IPC testable without a GPU context.  `_remove_client`
  currently calls into scene ownership transfer -- that callback
  becomes an `on_client_disconnected: Callable[[int], None]`
  parameter on the constructor.  SocketServer must not import
  SceneManager.

### SceneManager

- **Status**: PROPOSED
- **Module**: `punt_lux.scene_manager` (new)
- **Responsibility**: Own the scene graph -- frames, scenes, scene-to-frame mapping, widget state per scene, and the update/patch pipeline.
- **Compositions**:
  - Frame dataclass (promoted from `_Frame`)
  - WidgetState (one per scene)
- **Collaborations**:
  - DisplayServer -- renders scenes the manager provides
  - SocketServer -- receives SceneMessage/UpdateMessage/ClearMessage
  - ElementRenderer -- queries scene content for rendering
- **Key methods**:
  - `handle_scene(fd: int, msg: SceneMessage) -> AckMessage`
  - `handle_framed_scene(fd: int, msg: SceneMessage) -> AckMessage`
  - `upsert_scene_in_frame(frame_id: str, scene_id: str, elements: list[Element]) -> None`
  - `apply_update(scene_id: str, patches: list[Patch]) -> AckMessage`
  - `resolve_scene(scene_id: str) -> list[Element] | None`
  - `dismiss_scene(scene_id: str) -> None`
  - `close_frame(frame_id: str) -> None`
  - `clear_all() -> None`
  - `current_widget_state(scene_id: str) -> WidgetState`
- **Related functions (to move from DisplayServer)**:
  - `_handle_scene`, `_handle_framed_scene`
  - `_upsert_scene_in_frame`, `_resolve_scene`
  - `_apply_update`, `_apply_patch_set`
  - `_replace_scene_state`
  - `_dismiss_scene`, `_dismiss_framed_scene`, `_close_frame`
  - `_next_cascade_index`
- **State to move from DisplayServer**:
  - `_scenes`, `_scene_order`, `_active_tab`
  - `_frames`, `_focus_frame_id`, `_scene_to_frame`, `_scene_to_owner`
  - `_scene_widget_state`, `_dirty_windows`
- **Notes**: Largest extraction, highest testability gain.  The scene
  graph is a pure state machine with no ImGui, no socket, no OpenGL
  dependency.  Every operation can be unit-tested against dict
  assertions.

  `_replace_scene_state` currently drains stale events from the event
  queue.  SceneManager must not own the event queue -- that stays on
  DisplayServer where `_flush_events` lives.  SceneManager receives
  an `on_scene_replaced(stale_scene_ids: list[str])` callback, and
  DisplayServer drains its own queue.  This keeps the event queue in
  the coordinator where it belongs.

### MenuManager

- **Status**: PROPOSED
- **Module**: `punt_lux.menu_manager` (new)
- **Responsibility**: Own all menu state -- the Lux menu, Applications menu, Window menu, Help menu, World panel, agent menus, and per-client menu registrations.  Render menus.  Dispatch menu-click events via callbacks.
- **Compositions**: None (menu items are dicts)
- **Collaborations**:
  - DisplayServer -- calls `render_menus()` in the ImGui callback
  - SocketServer -- receives MenuMessage, RegisterMenuMessage
  - SceneManager -- window menu items (collapse all, fit all) act on frames
- **Key methods**:
  - `show_menus(imgui_context: Any) -> None`
  - `handle_register_menu(fd: int, msg: RegisterMenuMessage) -> None`
  - `handle_menu_message(msg: MenuMessage) -> None`
  - `render_world_panel() -> None`
- **Related functions (to move from DisplayServer)**:
  - `_show_menus`, `_show_lux_menu`, `_show_lux_items`
  - `_show_apps_menu`, `_show_window_menu`, `_show_window_frame_items`, `_show_window_chrome_items`
  - `_show_help_menu`, `_show_help_items`
  - `_show_agent_menu`
  - `_check_world_menu_background_click`
  - `_render_world_panel`, `_render_world_panel_sections`, `_render_world_panel_apps`
  - `_handle_register_menu`, `_sanitize_menu_items`
  - `_sorted_app_clients`, `_render_registered_item`, `_display_name`
- **State to move from DisplayServer**:
  - `_agent_menus`, `_menu_registrations`, `_menu_owners`
  - `_world_menu_open`, `_world_menu_pinned`, `_world_menu_spawn_pos`
- **State that stays on DisplayServer** (not menu state):
  - `_themes`, `_current_theme` -- display-wide theme state
  - `_decorated`, `_opacity`, `_font_scale` -- window chrome state
- **Notes**: ~350 lines after removing theme/chrome ownership.
  MenuManager receives callbacks for "user selected theme X" and
  "user toggled decorated" -- it renders the UI for those settings
  but does not own the state.  This keeps the invariant clean:
  MenuManager owns menu registrations and renders menus.

### ElementRenderer

- **Status**: PROPOSED
- **Module**: `punt_lux.element_renderer` (new)
- **Responsibility**: Render protocol Element dataclasses as ImGui widgets.  One method per element kind.  Dispatch by kind string via the existing `_RENDERERS` class variable.
- **Compositions**: None
- **Collaborations**:
  - DisplayServer / SceneManager -- provides elements + widget state
  - WidgetState -- reads/writes interactive widget values
  - TextureCache -- image rendering
  - `emit_event: Callable[[InteractionMessage], None]` -- emits events
- **Key methods**:
  - `render_element(element: Element, scene_id: str) -> None`
  - 24 `_render_*` methods (one per element kind)
- **Constructor dependencies** (three, not two):
  - `widget_state: WidgetState`
  - `texture_cache: TextureCache`
  - `emit_event: Callable[[InteractionMessage], None]`
- **Related functions (to move from DisplayServer)**:
  - `_render_element` (dispatch entry point)
  - All 24 `_render_*` methods
  - `_render_text_tooltip`, `_parse_hex_color`, `_resolve_arrow_dir`
  - `_RENDERERS` class variable
- **Notes**: ~1,200 lines.  The renderer is the Visitor pattern
  applied to element kinds: one method per kind, dispatch by kind
  string.  It has one responsibility (render elements) and no
  cross-cutting state.  Each `_render_*` method is independent --
  the class is a flat namespace with shared dependencies, not a god
  object.

  DisplayServer sets `element_renderer.widget_state =
  scene_manager.current_widget_state(scene_id)` before each scene
  render.  This handoff is explicit.  WidgetState is not a shared
  mutable reference threaded through multiple layers.

  **Needs ImGui** -- cannot be unit-tested without a GPU context or
  ImGui mock.

### TableRenderer

- **Status**: PROPOSED
- **Module**: `punt_lux.table_renderer` (new, or nested in element\_renderer)
- **Responsibility**: Render the `table` element kind -- filters, pagination, row selection, detail panel, column sizing, keyboard navigation, copy-to-clipboard.
- **Compositions**: None
- **Collaborations**:
  - ElementRenderer -- delegates `_render_table` to this class
  - WidgetState -- filter state, selection state, page state
- **Key methods**:
  - `render(table: TableElement, scene_id: str) -> None`
  - `apply_filters(rows: list, filters: list[TableFilter]) -> list`
  - `render_pagination(total_rows: int) -> tuple[int, int]`
  - `render_rows(columns: list[str], rows: list, flags: list[str]) -> int | None`
  - `render_detail(detail: TableDetail, selected_row: int) -> None`
- **Related functions (to move from module-level in display.py)**:
  - `_render_filter_search`, `_render_filter_combo`
  - `_get_filter_snapshot`, `_apply_table_filters`, `_filter_indexed_rows`, `_filter_combo`
  - `_render_table_pagination`, `_maybe_copy_id`
  - `_parse_table_flags`, `_render_table_rows`, `_handle_table_keyboard_nav`
  - `_render_table_detail`, `_render_detail_field_grid`, `_table_column_weights`
  - `IndexedRow` type alias, `_ROWS_PER_PAGE` constant
- **Notes**: 450 lines of module-level functions that all take the same
  parameters: `widget_state`, `table_id`, `imgui`.  This is a class
  that has been spelled as free functions.  Making it a class
  eliminates the repeated parameter passing.  The constructor takes
  `widget_state` and `imgui`; `table_id` is a method parameter (one
  instance serves multiple tables in a single frame).

  **Needs ImGui** -- but the filter logic (`_apply_table_filters`,
  `_filter_indexed_rows`, `_filter_combo`) is pure Python and can
  be tested without ImGui.

### QueryDispatcher

- **Status**: PROPOSED
- **Module**: `punt_lux.query_dispatcher` (new)
- **Responsibility**: Route `QueryRequest` messages to handler methods and return `QueryResponse`.  Own the ring buffers for events and errors (for introspection only).
- **Compositions**: None
- **Collaborations**:
  - DisplayServer -- registers handlers in `__init__`, receives query messages from socket layer
  - SceneManager -- many queries inspect scene state
  - MenuManager -- `list_menus`, `list_clients` query menu state
- **Key methods**:
  - `handle_query(fd: int, msg: QueryRequest) -> QueryResponse`
  - `register_handler(method: str, handler: Callable) -> None`
  - `record_event(event: InteractionMessage) -> None`
  - `record_error(error: dict) -> None`
- **Related functions (to move from DisplayServer)**:
  - `_handle_query`
  - `_query_inspect_scene`, `_query_list_scenes`, `_query_screenshot`
  - `_query_get_display_info`, `_query_get_window_settings`, `_query_get_theme`
  - `_query_list_clients`, `_query_list_menus`
  - `_query_list_recent_events`, `_query_list_errors`
  - `_query_set_window_settings`, `_query_set_frame_state`, `_query_set_theme`
  - `_record_error`
- **State to move from DisplayServer**:
  - `_query_handlers` dict
  - `_recent_events` deque (ring buffer, for introspection only)
  - `_recent_errors` deque (ring buffer)
- **Notes**: ~250 lines.  Handlers need read access to scene/menu/window
  state -- they receive those managers as constructor dependencies,
  not by reaching into `self._scenes`.

  The event flow after extraction: ElementRenderer and MenuManager
  receive an `emit_event: Callable[[InteractionMessage], None]`
  callback.  DisplayServer owns the event queue and `_flush_events`.
  QueryDispatcher reads the ring buffer for `list_recent_events`.
  No separate EventBus class is needed -- the callback pattern is
  sufficient.

  **No ImGui dependency** -- fully unit-testable.

### Message routing (not a class)

The current `_handle_message` is a 40-line if/elif chain.  After the
other extractions, it becomes a thin dispatcher:

```python
def _handle_message(self, fd: int, msg: Message) -> None:
    if isinstance(msg, SceneMessage):
        ack = self._scene_manager.handle_scene(fd, msg)
        self._socket_server.send_to_client(fd, ack)
    elif isinstance(msg, UpdateMessage):
        ack = self._scene_manager.apply_update(msg.scene_id, msg.patches)
        self._socket_server.send_to_client(fd, ack)
    elif isinstance(msg, QueryRequest):
        resp = self._query_dispatcher.handle_query(fd, msg)
        self._socket_server.send_to_client(fd, resp)
    # ... 1-2 lines per message type
```

This is a method on DisplayServer, not a class.  A separate
MessageRouter class for a stateless 40-line method that holds no
state and enforces no invariant is a namespace, not a class.

---

## protocol.py decomposition

### Current state

56 dataclasses (24 element types, 6 client message types, 8 display
message types, plus Patch, TableFilter, TableDetail, and the union
aliases) plus 73 module-level serialization functions organized as a
parallel hierarchy: `_image_to_dict`, `_image_from_dict`,
`_text_to_dict`, `_text_from_dict`, etc.

The module has three structural problems:

1. `message_from_dict` is a 95-line if/elif chain (line 1655).
2. `element_from_dict` dispatches through `_ELEMENT_DESERIALIZERS` -- this is already a registry, but the parallel `_ELEMENT_SERIALIZERS` dict (line 1085) and the 24 `_*_to_dict` / 24 `_*_from_dict` function pairs are manually maintained.
3. `_register_serializers` (line 1515) is a 120-line closure factory that populates a module-global dict.  Each inner function is 2-6 lines.  The closure pattern exists solely to avoid repeating `_MESSAGE_SERIALIZERS[X] = ...` at module scope.

### ElementCodec

- **Status**: PROPOSED
- **Module**: `punt_lux.protocol` (stays)
- **Responsibility**: Serialize Element dataclasses to dicts and deserialize dicts to Elements.  Replace the 48 module-level `_*_to_dict` / `_*_from_dict` functions and the two dispatch dicts.
- **Compositions**: None
- **Collaborations**:
  - Every Element dataclass -- registered via `__init_subclass__`
  - `element_from_dict` / `element_to_dict` -- become module-level wrappers around the singleton
- **Key methods**:
  - `to_dict(elem: Element) -> dict[str, Any]`
  - `from_dict(data: dict[str, Any]) -> Element`
  - `register(kind: str, cls: type, to_fn: Callable, from_fn: Callable) -> None`
- **Design**: `__init_subclass__` registration

The concrete design uses `__init_subclass__` on a mixin so that each
element dataclass self-registers its codec pair:

```python
class _ElementBase:
    """Mixin that auto-registers element codecs via __init_subclass__."""

    _to_dict_fn: ClassVar[Callable[..., dict[str, Any]]]
    _from_dict_fn: ClassVar[Callable[[dict[str, Any]], Any]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        kind = cls.__dataclass_fields__["kind"].default  # type: ignore[attr-defined]
        if kind and hasattr(cls, "_to_dict_fn") and hasattr(cls, "_from_dict_fn"):
            _ELEMENT_SERIALIZERS[type(cls)] = cls._to_dict_fn  # type: ignore[arg-type]
            _ELEMENT_DESERIALIZERS[kind] = cls._from_dict_fn

@dataclass
class TextElement(_ElementBase):
    id: str
    content: str
    kind: Literal["text"] = "text"
    style: str | None = None
    tooltip: str | None = None
    color: str | None = None

    @staticmethod
    def _to_dict_fn(elem: TextElement) -> dict[str, Any]:
        return _strip_none({
            "kind": elem.kind,
            "id": elem.id,
            "content": elem.content,
            "style": elem.style,
            "color": elem.color,
        })

    @staticmethod
    def _from_dict_fn(d: dict[str, Any]) -> TextElement:
        return TextElement(
            id=d["id"],
            content=d.get("content", ""),
            style=d.get("style"),
            color=d.get("color"),
        )
```

However -- and the report must be honest about this -- the gain is
structural, not functional.  The current code works.  The free
functions are repetitive but each is under 20 lines.  The dispatch
dicts at lines 1085 and 1392 are already the right pattern, just
spelled at module scope.  The `__init_subclass__` version eliminates
the manual dict maintenance and puts serialization next to the
dataclass it serves, but the line count is roughly the same.

The real gain comes when plugins register new element kinds --
`__init_subclass__` makes that automatic.  If plugin extensibility
is not needed soon, this is lower priority than the display.py
decomposition.

**Rejected alternative**: `to_dict()` / `from_dict()` as instance
and class methods directly on the dataclasses, without a mixin or
registry.  This scatters the codec across 24 classes with no central
dispatch.  `element_from_dict(d)` would need to inspect `d["kind"]`
and then somehow find the right class.  A registry -- whether
module-level dicts or `__init_subclass__` -- is unavoidable for
deserialization.

### MessageCodec

- **Status**: PROPOSED
- **Module**: `punt_lux.protocol` (stays)
- **Responsibility**: Serialize and deserialize Message dataclasses.  Replace `message_to_dict`, `message_from_dict`, `_register_serializers`, and the `_MESSAGE_SERIALIZERS` dict.
- **Compositions**: None
- **Collaborations**:
  - Every Message dataclass
  - `encode_message`, `encode_frame` -- uses MessageCodec.to\_dict
  - FrameReader.drain\_typed -- uses MessageCodec.from\_dict
- **Key methods**:
  - `to_dict(msg: Message) -> dict[str, Any]`
  - `from_dict(data: dict[str, Any]) -> Message`

The concrete design replaces the 95-line `message_from_dict` if/elif
chain and the 120-line `_register_serializers` closure factory with a
type-string registry:

```python
_MESSAGE_CODECS: dict[str, tuple[type, Callable, Callable]] = {}


def _register_message(
    type_str: str,
    cls: type,
    to_fn: Callable[..., dict[str, Any]],
    from_fn: Callable[[dict[str, Any]], Any],
) -> None:
    _MESSAGE_CODECS[type_str] = (cls, to_fn, from_fn)
    _MESSAGE_SERIALIZERS[cls] = to_fn


def message_from_dict(d: dict[str, Any]) -> Message:
    msg_type = d.get("type", "")
    codec = _MESSAGE_CODECS.get(msg_type)
    if codec is not None:
        _, _, from_fn = codec
        return from_fn(d)
    if not isinstance(msg_type, str) or not msg_type:
        raise ValueError("Message missing or invalid 'type' field")
    return UnknownMessage(raw_type=msg_type, data=d)


# Registration -- replaces 120-line _register_serializers():

_register_message("scene", SceneMessage, _scene_to_dict, _scene_from_dict)
_register_message("update", UpdateMessage, _update_to_dict, _update_from_dict)
_register_message("clear", ClearMessage,
    lambda m: {"type": m.type},
    lambda d: ClearMessage())
_register_message("ping", PingMessage,
    lambda m: _ts_dict(m.type, m.ts),
    lambda d: PingMessage(ts=d.get("ts")))
# ... one line per message type
```

This replaces 215 lines (95-line `message_from_dict` + 120-line
`_register_serializers`) with ~40 lines of registration plus the
same `_*_to_dict` / `_*_from_dict` functions.  Net savings: ~100
lines, plus the if/elif chain is gone.

### FrameReader

- **Status**: EXISTS
- **Module**: `punt_lux.protocol`
- **Responsibility**: Accumulate bytes from a socket and yield complete length-prefixed messages.
- **Compositions**: Internal bytearray buffer
- **Collaborations**:
  - SocketServer / DisplayClient -- `feed()` with recv'd bytes, iterate `drain()`
- **Key methods**: `feed(data: bytes)`, `drain() -> list[dict]`, `drain_typed() -> list[Message]`, `buffer_size: int`
- **Notes**: Well-scoped.  No changes needed.

---

## tools.py decomposition

### Current state

29 MCP tool functions.  The module has two structural problems:

1. **15 query-wrapper tools** that follow an identical 12-line pattern
   (check `is_display_running`, get client, call `client.query(method,
   params)`, check response for None/error, format result as JSON).
   The unique logic per tool is 0-3 lines.

2. **Module-level state** (`_client`, `_client_lock`, `_session_key`,
   `_session_menus`, `_apps_registered_for`) that is a class waiting
   to be born.

### ToolState

- **Status**: PROPOSED
- **Module**: `punt_lux.tools` (stays)
- **Responsibility**: Own the module-level mutable state: the cached DisplayClient, the client lock, per-session menu tracking, and app registration tracking.
- **Compositions**:
  - DisplayClient (lazily created, cached)
- **Collaborations**:
  - MCP tool functions -- all tools call `state.get_client()` instead of module-level `_get_client()`
  - `_lifespan` -- calls `state.get_client()` for eager connect
  - `run_mcp_session` -- calls `state.cleanup_session(key)`
- **Key methods**:
  - `get_client() -> DisplayClient`
  - `with_reconnect(fn: Callable[[], T]) -> T`
  - `cleanup_session(session_key: str) -> None`
  - `setup_apps(client: DisplayClient) -> None`
- **State (moves from module level)**:
  - `_client: DisplayClient | None`
  - `_client_lock: threading.RLock`
  - `_session_key: ContextVar[str]`
  - `_session_menus: dict[str, list[str]]`
  - `_apps_registered_for: int | None`
- **Notes**: This class is optional -- the module-level state works.
  The gain is testability: a ToolState instance can be injected with
  a mock DisplayClient.  If testing tools.py is not a near-term goal,
  defer.  The query decorator (below) is higher priority.

### Query decorator

- **Status**: PROPOSED
- **Module**: `punt_lux.tools` (stays)
- **Responsibility**: Eliminate the repeated `is_display_running` check, `_get_client()`, `_with_reconnect`, `response.error` handling, and `json.dumps` formatting from the 15 query-wrapper tools.

**Concrete design:**

```python
import functools


def _query_tool(
    method: str,
    *,
    doc: str = "",
) -> Callable[..., Callable[..., str]]:
    """Decorator: wrap a param-builder as a query-based MCP tool.

    The decorated function returns a params dict (or None for no params).
    The decorator handles: running check, client acquisition, reconnect,
    response error handling, and JSON formatting.
    """

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

**Before** (each of 15 tools looks like this):

```python
@mcp.tool()
def get_display_info() -> str:
    """Return display server metadata."""
    if not is_display_running(default_socket_path()):
        return "not running"

    def _call() -> str:
        client = _get_client()
        response = client.query("get_display_info")
        if response is None:
            return "timeout"
        if response.error:
            return f"error: {response.error}"
        return json.dumps(response.result, indent=2)

    return _with_reconnect(_call)
```

**After** (all 15 become 3-10 lines):

```python
@_query_tool("get_display_info")
def get_display_info() -> None:
    """Return display server metadata: backend, resolution, FPS, PID, uptime."""


@_query_tool("list_recent_events")
def list_recent_events(count: int = 50) -> dict[str, Any] | None:
    """Return the last N interaction events from the display."""
    return {"count": count}
```

**Savings**: ~150 lines of boilerplate eliminated.

---

## display\_client.py decomposition

### Current state

DisplayClient has 692 lines, 35 methods, and one clear
responsibility: display protocol client.  The structural problem is
not decomposition but migration.  Six response queues exist
(`_ack_queue`, `_pong_queue`, `_introspect_queue`,
`_list_scenes_queue`, `_screenshot_queue`, `_query_queue`), each
with a parallel blocking method.  The `query()` method (line 610)
was added to generalize this, and it works: all new introspection
operations use `query()`.

### DisplayClient (after migration)

- **Status**: EXISTS -- NEEDS MIGRATION
- **Module**: `punt_lux.display_client`
- **Responsibility**: Connect to the display server over a Unix socket, send typed messages, receive responses with timeout, dispatch callbacks on a background listener thread.
- **Compositions**:
  - FrameReader -- message framing
  - Background listener thread
  - `_ack_queue` (stays -- show/update need dedicated ack routing)
  - `_pong_queue` (stays -- ping needs dedicated pong routing)
  - `_query_queue` (stays -- generic query response routing)
- **Collaborations**:
  - tools.py -- `_get_client()` returns a DisplayClient
  - show.py / beads.py -- CLI callers
  - protocol.py -- all message types

**Methods that go (migrate to `query()`):**

| Method | Replacement |
|--------|-------------|
| `inspect_scene(scene_id)` | `query("inspect_scene", {"scene_id": scene_id})` |
| `list_scenes()` | `query("list_scenes")` |
| `screenshot()` | `query("screenshot")` |

**Queues that go:**

| Queue | Current consumer | After migration |
|-------|-----------------|-----------------|
| `_introspect_queue` | `inspect_scene()` | Removed -- `query()` uses `_query_queue` |
| `_list_scenes_queue` | `list_scenes()` | Removed |
| `_screenshot_queue` | `screenshot()` | Removed |

DisplayClient shrinks by ~100 lines and 3 queues after the
migration.  The three legacy methods become thin deprecated wrappers
that call `query()` and adapt the response.

---

## \_\_main\_\_.py -- CLI coordinator

### Current state

572 lines, 22 CLI commands registered on a flat `typer.Typer` app.
Comment headers partition the commands into implicit groups:

- **Product commands** (lines 66-133): `display`, `serve`, `enable`, `disable`
- **Hook dispatcher** (lines 140-157): `hook session-start`, `hook post-bash`
- **Admin commands** (lines 164-568): `version`, `ping`, `status`, `doctor`,
  `hub-install`, `hub-uninstall`, `ensure-hub`, `hub-status`, `setup-proxy`,
  `install`, `uninstall`

The module has three separate responsibilities embedded in one file:

1. **CLI wiring** -- creating the `typer.Typer` app, registering commands,
   and the `_main` callback
2. **Doctor checks** -- `_check_fonts`, `_check_plugin`, and the `doctor`
   command body (100 lines of platform-specific font resolution)
3. **Hub restart logic** -- `_restart_hub` (50 lines of signal/sleep/retry)

### Why the current design is wrong

In the merchants reference, `Game` is the facade that wires
`RoundController`, `Captain`, `Deck`, and `SeazoneBuilder` together.
Nobody asks "what coordinates the CLI?" because `Game.__new__` is
that coordinator.  In Lux, the CLI file is the equivalent of `Game` --
it wires `display`, `service`, `hub`, `config`, `hooks`, `show`, and
`remote` together.

The problem is not that the file has 22 commands.  Typer is designed
for flat command registration.  The problem is that non-trivial logic
lives inline in command bodies instead of in the modules they belong
to.  The `doctor` command does 100 lines of font probing that belongs
in a `DoctorChecker` class.  The `_restart_hub` function does 50
lines of signal/sleep/retry that belongs in `service.py` or `hub.py`.

### 1. DoctorChecker

- **Status**: PROPOSED
- **Module**: `punt_lux.doctor` (new)
- **Responsibility**: Run health checks against the Lux installation and report results.
- **Single responsibility**: Collect and report diagnostic checks -- font availability, Python version, imgui-bundle, display server, Claude plugin.

```python
@dataclass
class CheckResult:
    """One diagnostic check result."""
    symbol: str  # _OK, _FAIL, _OPTIONAL
    message: str
    required: bool = True


class DoctorChecker:
    """Run installation health checks and collect results.

    State: accumulated check results.
    Collaborations: paths.py (display running), shutil (claude CLI).
    """

    def __init__(self, socket_path: Path | None = None) -> None:
        self._socket_path = socket_path
        self._results: list[CheckResult] = []

    def check_python_version(self) -> None: ...
    def check_imgui_bundle(self) -> None: ...
    def check_fonts(self) -> None: ...
    def check_display_server(self) -> None: ...
    def check_plugin(self) -> None: ...
    def run_all(self) -> None: ...

    @property
    def results(self) -> list[CheckResult]: ...

    @property
    def passed(self) -> int: ...

    @property
    def failed(self) -> int: ...
```

**Before** (`__main__.py`, excerpt):

```python
@app.command()
def doctor(socket: str | None = ...) -> None:
    passed = 0
    failed = 0
    lines: list[str] = []

    def _check(symbol, message, *, required=True):
        nonlocal passed, failed
        lines.append(f"{symbol} {message}")
        # ... counting logic

    # 100 lines of inline checks including font probing
    _check_fonts(_check)
    _check_plugin(_check)
    # ... print results
```

**After**:

```python
@app.command()
def doctor(socket: str | None = ...) -> None:
    from punt_lux.doctor import DoctorChecker

    checker = DoctorChecker(socket_path=Path(socket) if socket else None)
    checker.run_all()
    checker.print_report()
    if checker.failed > 0:
        raise typer.Exit(code=1)
```

The command body drops from 65 lines to 7.  `_check_fonts` and
`_check_plugin` move to methods on `DoctorChecker`.  The `_CheckFn`
protocol type is eliminated -- the checker owns its own result
accumulation.

### 2. Hub restart -- moves to service.py

`_restart_hub` (lines 412-460) is a 50-line function that sends
SIGTERM, waits for the old process to die, and waits for the service
manager to respawn a new process.  This is daemon lifecycle management
-- exactly what `service.py` already owns.

```python
# In service.py:
def restart() -> str:
    """Restart luxd by sending SIGTERM and waiting for respawn.

    Returns a status message. Raises SystemExit on failure.
    """
    ...
```

The `ensure-hub` command becomes:

```python
@app.command("ensure-hub")
def ensure_hub(restart: bool = ...) -> None:
    if restart and is_hub_running():
        from punt_lux.service import restart as service_restart
        print(service_restart())
        return
    # ... existing status check
```

### 3. Command grouping -- Typer sub-apps

The 5 hub commands (`hub-install`, `hub-uninstall`, `ensure-hub`,
`hub-status`, `setup-proxy`) share a `hub-` prefix and all delegate
to `service.py` or `hub.py`.  They should be a Typer sub-app:

```python
hub_app = typer.Typer(help="Hub daemon management.")
app.add_typer(hub_app, name="hub")

@hub_app.command("install")
def hub_install() -> None: ...

@hub_app.command("uninstall")
def hub_uninstall() -> None: ...

@hub_app.command("status")
def hub_status() -> None: ...

@hub_app.command("ensure")
def ensure_hub(restart: bool = ...) -> None: ...

@hub_app.command("setup-proxy")
def setup_proxy(url: str = ...) -> None: ...
```

This changes `lux hub-install` to `lux hub install`, which is a
better CLI taxonomy.  The hook commands already use this pattern
(`hook_app = typer.Typer(hidden=True)`).

### What stays in \_\_main\_\_.py

After these extractions, `__main__.py` is ~300 lines: the `app`
creation, the `_main` callback, each command as a 5-15 line function
that imports the right module and delegates.  This is the same
pattern as merchants' `Game.__new__` -- a wiring coordinator that
owns no domain logic.

A `CLIApp` class wrapping the Typer app is not warranted.  Typer
already provides the command-registration mechanism, the help
generation, and the callback dispatch.  Wrapping it in a class adds
a `self` parameter with no encapsulated state to justify it --
Typer's `app` instance *is* the state.

---

## service.py -- ServiceManager with platform strategies

### Current state

347 lines, 14 functions.  Two platform backends (launchd on macOS,
systemd on Linux) with parallel function sets:

```text
_launchd_plist_content  /  _systemd_unit_content
_launchd_install        /  _systemd_install
_launchd_uninstall      /  _systemd_uninstall
_launchd_status         /  _systemd_status
```

Plus shared helpers: `_luxd_exec_args`, `detect_platform`,
`_has_linger`, and the public API (`install`, `uninstall`).

The public API dispatches via `if plat == "macos" ... else ...`,
exactly mirroring the manual vtable that a Strategy pattern
eliminates.

### ServiceBackend (ABC) + LaunchdBackend + SystemdBackend

```python
from abc import ABC, abstractmethod
from pathlib import Path


class ServiceBackend(ABC):
    """Platform-specific daemon lifecycle strategy.

    Single responsibility: install, uninstall, and check status of
    the luxd service via the platform's service manager.
    """

    @abstractmethod
    def install(self, exec_args: list[str]) -> None:
        """Write the service config and load the daemon."""

    @abstractmethod
    def uninstall(self) -> None:
        """Stop the daemon and remove the service config."""

    @abstractmethod
    def is_active(self) -> bool:
        """Whether the service is currently running."""

    @abstractmethod
    def config_path(self) -> Path:
        """Path to the service config file."""


class LaunchdBackend(ServiceBackend):
    """macOS launchd implementation.

    State: _LAUNCHD_DIR, _LAUNCHD_PLIST (constants).
    Collaborations: subprocess (launchctl), pathlib (file I/O).
    """

    def __init__(self) -> None:
        self._plist_dir = Path.home() / "Library" / "LaunchAgents"
        self._plist_path = self._plist_dir / "com.punt-labs.lux.plist"

    def install(self, exec_args: list[str]) -> None: ...
    def uninstall(self) -> None: ...
    def is_active(self) -> bool: ...
    def config_path(self) -> Path:
        return self._plist_path


class SystemdBackend(ServiceBackend):
    """Linux systemd user unit implementation.

    State: _SYSTEMD_DIR, _SYSTEMD_UNIT (constants).
    Collaborations: subprocess (systemctl), pathlib (file I/O).
    """

    def __init__(self) -> None:
        self._unit_dir = Path.home() / ".config" / "systemd" / "user"
        self._unit_path = self._unit_dir / "lux.service"

    def install(self, exec_args: list[str]) -> None: ...
    def uninstall(self) -> None: ...
    def is_active(self) -> bool: ...
    def config_path(self) -> Path:
        return self._unit_path
```

### ServiceManager

```python
class ServiceManager:
    """Coordinate daemon lifecycle across platforms.

    Single responsibility: resolve the platform backend and
    delegate install/uninstall/restart/status operations.

    State: _backend (the resolved ServiceBackend).
    Collaborations: ServiceBackend (strategy), _luxd_exec_args
    (binary resolution).
    """

    def __init__(self) -> None:
        self._backend = self._resolve_backend()

    @staticmethod
    def _resolve_backend() -> ServiceBackend:
        system = platform.system()
        if system == "Darwin":
            return LaunchdBackend()
        if system == "Linux":
            return SystemdBackend()
        msg = f"Unsupported platform: {system}"
        raise SystemExit(msg)

    def install(self) -> str:
        args = _luxd_exec_args()
        self._backend.install(args)
        running = self._backend.is_active()
        # ... build status message

    def uninstall(self) -> str:
        self._backend.uninstall()
        return f"luxd uninstalled. Removed {self._backend.config_path()}."

    def restart(self) -> str:
        """Send SIGTERM and wait for the service manager to respawn.
        Moved from __main__.py._restart_hub."""
        ...

    @property
    def is_active(self) -> bool:
        return self._backend.is_active()
```

**Before** (`service.py`, public API):

```python
def install() -> str:
    plat = detect_platform()
    args = _luxd_exec_args()
    if plat == "macos":
        _launchd_install()
        running = _launchd_status()
    else:
        _systemd_install()
        running = _systemd_status()
    # ... build message

def uninstall() -> str:
    plat = detect_platform()
    if plat == "macos":
        _launchd_uninstall()
        path = _LAUNCHD_PLIST
    else:
        _systemd_uninstall()
        path = _SYSTEMD_UNIT
    return f"luxd uninstalled. Removed {path}."
```

**After**:

```python
_manager = ServiceManager()

def install() -> str:
    return _manager.install()

def uninstall() -> str:
    return _manager.uninstall()
```

The public API functions remain as module-level wrappers for backward
compatibility.  The class provides testability: inject a
`MockBackend(ServiceBackend)` that does not call `launchctl` or
`systemctl`.

### Why classes are right here

The parallel function sets (`_launchd_install` / `_systemd_install`,
etc.) are the defining symptom of the Strategy pattern.  Each set
operates on the same state (paths, service label) and provides the
same operations (install, uninstall, status).  The `if plat ==
"macos"` dispatching is a manual vtable.  Replacing it with
polymorphic dispatch eliminates the dispatching boilerplate, makes
adding a third platform (FreeBSD, container) a single new class, and
makes each backend testable in isolation.

---

## hub.py -- SessionHub

### Current state

224 lines, 8 functions.  Module-level mutable state:

```python
_active_sessions: set[str] = set()
```

Route handlers (`_health_route`, `_mcp_websocket_route`) read and
write `_active_sessions`.  The `build_app` factory creates a
Starlette app.  The `serve` function binds the socket and runs
uvicorn.

### SessionHub

```python
class SessionHub:
    """WebSocket session multiplexer for luxd.

    Single responsibility: track connected MCP sessions and
    provide the Starlette ASGI app that serves them.

    State:
      _active_sessions: set[str] -- session keys of connected clients
      _app: Starlette -- the ASGI application

    Collaborations:
      tools.run_mcp_session -- delegates MCP protocol handling
      uvicorn -- HTTP/WebSocket server
    """

    def __init__(self) -> None:
        self._active_sessions: set[str] = set()
        self._app = self._build_app()

    def _build_app(self) -> Starlette:
        """Build the Starlette ASGI application with routes and middleware."""
        ...

    async def _health_route(self, request: Request) -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "sessions": len(self._active_sessions),
        })

    async def _mcp_websocket_route(self, websocket: WebSocket) -> None:
        """MCP JSON-RPC over WebSocket for mcp-proxy."""
        ...
        self._active_sessions.add(session_key)
        try:
            ...
        finally:
            self._active_sessions.discard(session_key)

    @property
    def session_count(self) -> int:
        return len(self._active_sessions)

    def serve(self, host: str = "127.0.0.1", port: int = 8430) -> None:
        """Start the hub. Blocks until shutdown."""
        ...
```

**Before** (module-level state):

```python
_active_sessions: set[str] = set()

async def _health_route(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "sessions": len(_active_sessions)})
```

**After**:

```python
hub = SessionHub()

async def _health_route(request: Request) -> JSONResponse:
    return hub._health_route(request)

# Or more cleanly, build_app() references hub methods directly.
```

### Why a class is right here

`_active_sessions` is module-level mutable state shared between two
route handlers.  This is the textbook definition of state that should
be encapsulated.  The module-level `set` works today because there
is exactly one hub instance per process, but:

1. Testing requires resetting module-level state between tests
   (fragile).
2. Adding a second piece of shared state (e.g., session metadata,
   rate limiting) means another module-level variable and more
   functions that implicitly share it.
3. The Starlette app factory `build_app` already hints at the class --
   it returns an app object that *should* be owned by the thing that
   tracks sessions.

The `serve` function and the `main` entry point stay as module-level
functions that create a `SessionHub` and call `hub.serve()`.  The
class does not replace the entry points; it provides the state
container they need.

---

## paths.py -- DisplayPaths and HubPaths

### Current state

172 lines, 13 functions.  Two distinct groups with zero shared state
and zero shared logic:

**Display paths** (8 functions):

- `default_socket_path() -> Path`
- `pid_file_path(socket_path) -> Path`
- `log_file_path(socket_path) -> Path`
- `is_display_running(socket_path) -> bool`
- `cleanup_stale_socket(socket_path) -> None`
- `ensure_display(socket_path, timeout) -> Path`
- `write_pid_file(socket_path) -> None`
- `remove_pid_file(socket_path) -> None`

**Hub paths** (5 functions):

- `hub_dir() -> Path`
- `hub_pid_path() -> Path`
- `hub_port_path() -> Path`
- `hub_log_dir() -> Path`
- `read_hub_port() -> int | None`
- `is_hub_running() -> bool`

### Analysis

The display path functions operate on a `socket_path: Path` parameter
threaded through every call.  Six of the eight functions take this
parameter.  This is a cohesive group that shares an identity (the
socket path) and provides operations on that identity -- the classic
signal that a class provides value.

The hub path functions compute fixed paths under `~/.punt-labs/lux/`.
They take no parameters.  They are stateless pure functions derived
from constants.

### DisplayPaths

```python
class DisplayPaths:
    """Path resolution and lifecycle for a display server instance.

    Single responsibility: given a socket path, derive all related
    paths (pid file, log file) and manage the process lifecycle
    (is_running, cleanup, ensure, write_pid, remove_pid).

    State: socket_path (the identity of the display instance).
    Collaborations: subprocess (spawning display), os (process checks).
    """

    def __init__(self, socket_path: Path | None = None) -> None:
        self._socket_path = socket_path or self._default_path()

    @staticmethod
    def _default_path() -> Path:
        """Resolution: $LUX_SOCKET > $XDG_RUNTIME_DIR > /tmp."""
        ...

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    @property
    def pid_path(self) -> Path:
        return self._socket_path.with_suffix(".sock.pid")

    @property
    def log_path(self) -> Path:
        return self._socket_path.with_suffix(".sock.log")

    def is_running(self) -> bool: ...
    def cleanup_stale(self) -> None: ...
    def ensure(self, timeout: float = 5.0) -> Path: ...
    def write_pid(self) -> None: ...
    def remove_pid(self) -> None: ...
```

**Before** (threading socket_path everywhere):

```python
path = default_socket_path()
if is_display_running(path):
    pid = pid_file_path(path).read_text().strip()
    log = log_file_path(path)
```

**After**:

```python
display = DisplayPaths()
if display.is_running():
    pid = display.pid_path.read_text().strip()
    log = display.log_path
```

The parameter threading is eliminated.  The socket path is set once
in the constructor and derived paths are properties.

### Hub paths -- remain as functions

The 5 hub path functions are stateless pure functions that compute
paths from a fixed base directory (`~/.punt-labs/lux/`).  They take
no parameters.  They share no mutable state.  A `HubPaths` class
would add a `self` parameter with no encapsulated state to justify it
-- the class would be a namespace, not an object.

**Principle**: These are stateless pure functions operating on
immutable constants with no shared mutable state.  A class would add
a `self` parameter that carries no information the caller does not
already have.  The module is the namespace.

The existing `hub_dir`, `hub_pid_path`, `hub_port_path`,
`hub_log_dir`, `read_hub_port`, and `is_hub_running` stay as
module-level functions.  They could move to a separate `hub_paths.py`
module for clarity, but that is an organizational choice, not a
design one.

---

## config.py -- ConfigManager

### Current state

186 lines.  `LuxConfig` is a frozen dataclass with one field
(`display`).  Five module-level functions handle path resolution,
reading, and writing:

- `resolve_config_path() -> Path` (cached)
- `read_field(field, config_path) -> str | None`
- `read_config(config_path) -> LuxConfig`
- `write_field(key, value, config_path) -> None`
- `_extract_frontmatter(text) -> str`

### Analysis

`LuxConfig` is the data object.  The four public functions share a
`config_path` parameter (defaults to `DEFAULT_CONFIG_PATH` or the
resolved path).  The path resolution, reading, and writing form a
cohesive operation set on a single file.

### ConfigManager

```python
class ConfigManager:
    """Read and write .punt-labs/lux.md YAML frontmatter config.

    Single responsibility: own the config file path and provide
    typed read/write access to its YAML frontmatter fields.

    State: _config_path (resolved once, cached).
    Collaborations: pathlib (file I/O), re (frontmatter parsing).
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or resolve_config_path()

    @property
    def path(self) -> Path:
        return self._config_path

    def read(self) -> LuxConfig:
        """Read all config fields. Returns defaults when file is missing."""
        ...

    def read_field(self, field: str) -> str | None:
        """Read a single YAML frontmatter field."""
        ...

    def write_field(self, key: str, value: str) -> None:
        """Write a single field, preserving the file structure."""
        ...
```

**Before**:

```python
cfg = read_config(resolve_config_path())
write_field("display", "y", resolve_config_path())
```

**After**:

```python
config = ConfigManager()
cfg = config.read()
config.write_field("display", "y")
```

The path is resolved once in the constructor.  No repeated
`resolve_config_path()` calls.

### LuxConfig -- stays as-is

`LuxConfig` is a frozen data snapshot.  It has no behavior, no state
beyond its fields, and no methods to add.  It is the correct use of
a dataclass: a typed bag of values.  `ConfigManager.read()` returns
a `LuxConfig`.

### Why a class is right here

The four public functions share a `config_path` parameter that
defaults to the same resolved value.  Every call site either passes
`resolve_config_path()` explicitly or relies on the `DEFAULT_CONFIG_PATH`
fallback.  The path is the identity of the config file -- it should
be set once, not threaded through every call.  `ConfigManager`
encapsulates that identity.

The module-level functions can remain as backward-compatible wrappers
around a default `ConfigManager()` instance.

---

## hooks.py -- remains as functions

### Current state

127 lines, 4 functions:

- `handle_session_start() -> dict[str, object]`
- `read_hook_input() -> dict[str, object]`
- `handle_post_bash(data: dict[str, object]) -> None`
- `emit(output: dict[str, object]) -> None`

### Analysis

Each function is a pure handler:

- `handle_session_start`: reads config, returns a dict.  No mutable
  state, no side effects beyond the config read.
- `read_hook_input`: reads stdin with timeout.  No mutable state.
- `handle_post_bash`: checks a regex, reads config, optionally spawns
  a subprocess.  The config read is a query, the subprocess is
  fire-and-forget.
- `emit`: writes JSON to stdout.

**Principle**: These are stateless dispatcher functions.  Each takes
its input as a parameter and returns or emits its output.  There is
no shared mutable state between calls.  `handle_session_start` does
not remember anything from previous invocations.  `handle_post_bash`
does not accumulate state across calls.

A `HookDispatcher` class would encapsulate nothing.  The constructor
would take no arguments (or a `ConfigManager`, which
`handle_session_start` can construct locally).  The methods would have
no shared instance state.  The `self` parameter would carry no
information.

The Claude Code hook protocol is inherently stateless: each hook
invocation is a fresh process.  `lux hook session-start` is a
separate process from `lux hook post-bash`.  There is no persistent
state to encapsulate across invocations.

**Verdict**: No class.  The module is the namespace.  The functions
are correctly structured.

---

## remote.py -- ProxyConfigFile

### Current state

85 lines, 5 functions:

- `_toml_escape(value) -> str`
- `_serialize_config(config) -> str`
- `_atomic_write(content) -> None`
- `read_proxy_config() -> dict[str, Any]`
- `write_proxy_config(url) -> None`
- `delete_proxy_config() -> bool`

### Analysis

The three public functions (`read_proxy_config`, `write_proxy_config`,
`delete_proxy_config`) all operate on a single file:
`MCP_PROXY_CONFIG_PATH`.  They share atomic write logic and TOML
serialization.  The file path is a module-level constant.

### ProxyConfigFile

```python
class ProxyConfigFile:
    """Atomic read/write/delete for the mcp-proxy TOML config file.

    Single responsibility: manage the [lux] section in the mcp-proxy
    config file with atomic writes and TOML serialization.

    State: _path (the config file path).
    Collaborations: tomllib (reading), pathlib/os (atomic write).
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (Path.home() / ".punt-labs" / "mcp-proxy" / "lux.toml")

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> dict[str, Any]:
        """Return parsed TOML config, or {} if file does not exist."""
        ...

    def write(self, url: str) -> None:
        """Write [lux] section, preserving other sections."""
        ...

    def delete(self) -> bool:
        """Remove [lux] section. Return False if nothing to remove."""
        ...
```

**Before**:

```python
from punt_lux.remote import MCP_PROXY_CONFIG_PATH, write_proxy_config

write_proxy_config(url)
print(f"Wrote {MCP_PROXY_CONFIG_PATH}")
```

**After**:

```python
from punt_lux.remote import ProxyConfigFile

proxy = ProxyConfigFile()
proxy.write(url)
print(f"Wrote {proxy.path}")
```

### Why a class is right here

The three public functions share a file path and atomic write
mechanics.  The `_atomic_write` helper is effectively a private method.
The `_serialize_config` helper is effectively a private method.  The
TOML escape function is a static utility.  All of this is the internal
implementation of a single responsibility: managing a config file.

The module-level constant `MCP_PROXY_CONFIG_PATH` becomes the default
constructor argument.  Testing becomes straightforward: construct a
`ProxyConfigFile(tmp_path / "test.toml")` instead of monkeypatching
a module constant.

---

## apps/beads.py -- BeadsBrowser

### Current state

228 lines, 5 functions:

- `load_beads(*, all_issues) -> list[dict]`
- `build_beads_payload(issues) -> dict`
- `build_beads_elements(issues) -> list[Element]`
- `render_beads_board(client) -> None`

Plus constants (`_FIELD_DEFAULTS`).

### Analysis

Three distinct concerns are interleaved:

1. **Data loading**: `load_beads` -- subprocess call, JSON parsing,
   default-fill, sort.
2. **Table building**: `build_beads_payload`, `build_beads_elements`
   -- transform issue dicts into protocol elements.
3. **Rendering**: `render_beads_board` -- send elements to a
   DisplayClient.

### BeadsBrowser

```python
class BeadsBrowser:
    """Beads issue browser -- load, transform, and display issues.

    Single responsibility: provide the beads issue board as a
    self-contained display application.

    State: None persistent (stateless -- each call fetches fresh data).
    Collaborations: subprocess (bd CLI), protocol (Element types),
    DisplayClient (rendering).
    """

    FIELD_DEFAULTS: ClassVar[dict[str, Any]] = {
        "title": "",
        "status": "open",
        ...
    }

    def load(self, *, all_issues: bool = False) -> list[dict[str, Any]]:
        """Fetch, default-fill, filter, and sort issues via bd CLI."""
        ...

    def build_payload(self, issues: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the table element dict from issue data."""
        ...

    def build_elements(self, issues: list[dict[str, Any]]) -> list[Element]:
        """Build display elements from issue data."""
        ...

    def render(self, client: DisplayClient) -> None:
        """Send the beads issue board to the display."""
        issues = self.load()
        elements = self.build_elements(issues)
        client.show_async(...)
```

**Before** (menu callback in tools.py):

```python
def _on_beads_browser(_msg: InteractionMessage) -> None:
    if _client is None:
        return
    threading.Thread(target=render_beads_board, args=(_client,), daemon=True).start()
```

**After**:

```python
_beads_browser = BeadsBrowser()

def _on_beads_browser(_msg: InteractionMessage) -> None:
    if _client is None:
        return
    threading.Thread(target=_beads_browser.render, args=(_client,), daemon=True).start()
```

### Why a class is right here

The four functions form a pipeline: load -> build_payload ->
build_elements -> render.  The pipeline operates on a shared data
type (issue dicts) and a shared set of constants (`_FIELD_DEFAULTS`,
column names, filter specs).  The constants are configuration of the
browser, not module-level constants of the universe.

A class makes the pipeline explicit: `BeadsBrowser` is an application
object.  Future extension (e.g., configuration for which columns to
show, custom filters, different `bd` command flags) becomes instance
state on the class rather than new function parameters threaded
through the pipeline.

The module-level functions can remain as backward-compatible wrappers:

```python
_browser = BeadsBrowser()
load_beads = _browser.load
build_beads_payload = _browser.build_payload
build_beads_elements = _browser.build_elements
render_beads_board = _browser.render
```

---

## runtime.py -- existing classes reviewed

### RenderContext

- **Status**: EXISTS -- CORRECT
- **Module**: `punt_lux.runtime`
- **Responsibility**: Per-frame context passed to user-defined render functions.
- **State**: `state` (persistent dict), `dt`, `frame`, `width`, `height`, `_event_callback`.
- **Methods**: `send(action, data)` -- emit events back to the agent.
- **Collaborations**: `CodeExecutor` creates one per frame.
- **Notes**: Well-scoped.  `__slots__` is correctly used.  The
  `_event_callback` is the only mutable dependency and it is set once
  in the constructor.  No changes needed.

### CodeExecutor

- **Status**: EXISTS -- CORRECT
- **Module**: `punt_lux.runtime`
- **Responsibility**: Compile user-provided Python source, extract a `render(ctx)` function, call it each frame with error isolation.
- **State**: `source`, `_render_fn`, `_state`, `_frame`, `_error`, `_error_tb`, `_event_callback`.
- **Methods**: `render(dt, width, height)`, `hot_reload(new_source)`, `clear_error()`.
- **Collaborations**: Display server creates one per code element, calls `render()` each frame.
- **Notes**: Well-scoped.  `hot_reload` preserves state across source
  changes -- this is the correct factory method pattern.  Error
  isolation (try/except in `render()`) prevents user code from
  crashing the display loop.  No changes needed.

---

## \_\_init\_\_.py -- package exports

### Current state

107 lines.  Imports and re-exports 56 names from `protocol.py`,
`display_client.py`, and `paths.py`.  Provides the backward-compat
alias `LuxClient = DisplayClient`.

### Analysis

This is a public API surface definition.  It has no behavior, no
state, and no logic beyond `importlib.metadata.version()`.  It is not
a candidate for a class -- it is a namespace definition.

**Review for correctness**: The `__all__` list matches the imports.
`LuxClient` is correctly aliased.  `__version__` falls back to
`"0.0.0"` when not installed.  After any class renames or module
splits, the imports here must be updated, but the structure itself is
correct.

---

## show.py -- review

### Current state

58 lines.  One `typer.Typer` sub-app (`show_app`) with one command
(`beads`).  Re-exports `build_beads_elements`, `build_beads_payload`,
`load_beads` for backward compatibility.

### Analysis

The `beads` command creates a `DisplayClient`, calls
`build_beads_elements`, and sends the result via `client.show()`.
This is the CLI equivalent of `render_beads_board` in `beads.py`.

### Should `render_beads_board` live here instead of in beads.py?

No.  `render_beads_board` is a library function (takes a
`DisplayClient`, sends elements).  The `beads` CLI command is a CLI
entry point (creates its own client, handles socket paths, prints
feedback).  They serve different callers:

- `render_beads_board` is called by the menu callback in `tools.py`
  (already has a client).
- The `beads` CLI command is called by the user via `lux show beads`
  (creates its own client).

Merging them would conflate library and CLI concerns.  The current
split is correct.

### Class needed?

No.  `show.py` is a Typer sub-app with one command.  It delegates
to `beads.py` for data and to `DisplayClient` for rendering.  It has
no state, no shared logic between commands (there is only one
command), and Typer provides the registration mechanism.  A class
wrapping a single Typer command adds a `self` parameter with nothing
to encapsulate.

**Principle**: A module with one command function that delegates all
logic to other modules is a thin wiring layer.  The module is the
namespace.  This is correct.

---

## ImGui dependency map

Which extracted classes need ImGui (require a GPU context or mock for
testing) and which are pure Python:

| Class | ImGui required | Testable without GPU |
|-------|---------------|----------------------|
| SceneManager | No | Yes -- pure state machine |
| SocketServer | No | Yes -- socket I/O only |
| QueryDispatcher | No | Yes -- pure dispatch |
| TableRenderer (filter logic) | No | Yes -- `_apply_table_filters`, `_filter_indexed_rows` |
| TableRenderer (rendering) | Yes | No |
| ElementRenderer | Yes | No |
| MenuManager | Yes | No |
| ServiceManager | No | Yes -- mock ServiceBackend |
| DoctorChecker | No | Yes -- mock checks |
| SessionHub | No | Yes -- Starlette TestClient |
| DisplayPaths | No | Yes -- mock filesystem |
| ConfigManager | No | Yes -- tmp_path config file |
| ProxyConfigFile | No | Yes -- tmp_path config file |
| BeadsBrowser | No | Yes -- mock subprocess |

---

## Event flow after extraction

The event system is the primary cross-cutting concern.  Getting it
wrong creates circular dependencies.  Here is the explicit flow:

1. **Emit**: ElementRenderer and MenuManager receive an
   `emit_event: Callable[[InteractionMessage], None]` callback.
   When a user clicks a button or changes a slider, the renderer
   calls `emit_event(msg)`.

2. **Stamp**: DisplayServer's callback implementation stamps
   `scene_id` on the event (if not already set) and appends it to
   `_event_queue`.

3. **Record**: DisplayServer also calls
   `query_dispatcher.record_event(msg)` to populate the ring buffer
   for `list_recent_events`.

4. **Flush**: `_flush_events()` runs once per frame.  It iterates
   `_event_queue`, routes each event to the owning client's socket
   via `socket_server.send_to_client(fd, msg)`.  Menu-click events
   are routed to the client that registered the menu item.

No class imports another class.  All upward communication is
callbacks.  Dependency flow is strictly:

```text
DisplayServer
  -> SceneManager
  -> SocketServer
  -> ElementRenderer -> (callback) -> DisplayServer
  -> MenuManager     -> (callback) -> DisplayServer
  -> QueryDispatcher -> (reads ring buffer, no callback needed)
```

---

## Extraction priority

| Priority | Class | Source | LOC saved from display.py | Testability gain |
|----------|-------|--------|---------------------------|------------------|
| 1 | SceneManager | DisplayServer | ~250 | High -- pure state machine |
| 2 | SocketServer | DisplayServer | ~180 | High -- no ImGui dependency |
| 3 | TableRenderer | module-level fns | ~450 | High -- pure filter/pagination logic |
| 4 | QueryDispatcher | DisplayServer | ~250 | High -- pure dispatch |
| 5 | ElementRenderer | DisplayServer | ~1,200 | Medium -- needs ImGui mock |
| 6 | MenuManager | DisplayServer | ~350 | Medium -- ImGui rendering |
| 7 | query decorator | tools.py fns | ~150 boilerplate | N/A |
| 8 | DisplayClient migration | display\_client.py | ~100 + 3 queues | Medium |
| 9 | MessageCodec | protocol.py fns | ~100 | Low |
| 10 | ElementCodec | protocol.py fns | ~0 (structural) | Low |
| 11 | ServiceManager | service.py fns | ~0 (same LOC, better structure) | High |
| 12 | DoctorChecker | \_\_main\_\_.py | ~100 from \_\_main\_\_ | Medium |
| 13 | SessionHub | hub.py | ~0 (same LOC, encapsulated state) | Medium |
| 14 | DisplayPaths | paths.py fns | ~0 (same LOC, no param threading) | Medium |
| 15 | ConfigManager | config.py fns | ~0 (same LOC, path resolved once) | Medium |
| 16 | ProxyConfigFile | remote.py fns | ~0 (same LOC, testable path) | Medium |
| 17 | BeadsBrowser | beads.py fns | ~0 (same LOC, pipeline explicit) | Medium |

Extraction order rationale: each step must leave the system working.
Extract the cleanest boundaries first (pure state, socket I/O,
table logic, query dispatch) before the ImGui-coupled components
(renderer, menus).  The tools.py and DisplayClient changes are
independent of the display.py decomposition and can happen in
parallel.

After extractions 1-6, DisplayServer shrinks from 3,300 lines / 135
methods to approximately 600 lines / 20 methods.  display.py
(including module-level functions) shrinks from 4,208 lines to
approximately 900 lines.

### File layout after refactoring

```text
src/punt_lux/
    display.py           ~900 LOC  (DisplayServer: lifecycle + layout + message routing)
    socket_server.py     ~200 LOC  (SocketServer)
    scene_manager.py     ~300 LOC  (SceneManager + Frame)
    element_renderer.py  ~1200 LOC (ElementRenderer)
    table_renderer.py    ~500 LOC  (TableRenderer)
    menu_manager.py      ~400 LOC  (MenuManager)
    query_dispatcher.py  ~300 LOC  (QueryDispatcher)
    doctor.py            ~120 LOC  (DoctorChecker)
    protocol.py          ~1886 LOC (dataclasses + codec refactor)
    tools.py             ~900 LOC  (query decorator reduces boilerplate)
    display_client.py    ~600 LOC  (after query migration)
    __main__.py          ~300 LOC  (thin CLI wiring, hub sub-app)
    service.py           ~350 LOC  (ServiceManager + backends)
    hub.py               ~230 LOC  (SessionHub)
    paths.py             ~170 LOC  (DisplayPaths class + hub functions)
    config.py            ~190 LOC  (ConfigManager + LuxConfig)
    remote.py            ~90 LOC   (ProxyConfigFile)
    runtime.py           ~174 LOC  (RenderContext, CodeExecutor -- unchanged)
    hooks.py             ~127 LOC  (unchanged -- stateless dispatchers)
    show.py              ~58 LOC   (unchanged -- thin CLI wiring)
    apps/beads.py        ~230 LOC  (BeadsBrowser)
    __init__.py          ~110 LOC  (updated imports)
```

Total: ~10K LOC across ~23 files, largest module ~1,200 lines.
Compared to the merchants reference project's 2K/14/363 ratio, this
is larger, but the domain is fundamentally bigger (GUI rendering +
IPC protocol + MCP server vs. a board game).  The key metric is
that no class has more than one responsibility and no module is a
dependency bottleneck.

---

## Summary: modules that genuinely remain function-only

Two modules have no class and the report explains why with reference
to OO design principles:

### hooks.py

**Why no class**: Each function is invoked in a separate OS process
by the Claude Code hook protocol.  There is no persistent state
across invocations -- `handle_session_start` runs in one process,
`handle_post_bash` in another.  The functions take their input as
parameters and return or emit output.  No mutable state is shared
between calls within a single invocation.  A `HookDispatcher` class
would add a `self` parameter that encapsulates nothing -- the
constructor would take no arguments and the methods would reference
no instance state.  Per the Single Responsibility Principle, a class
with no state and no invariant to maintain is a namespace, and the
module already provides that namespace.

### show.py

**Why no class**: One Typer command that delegates all logic to
`beads.py` (data) and `DisplayClient` (rendering).  No state, no
shared logic between commands (there is only one command), no
parameter threading.  Typer's `show_app` object is the registration
mechanism.  A wrapper class around a single command function adds
a `self` parameter with nothing to encapsulate.

Every other module either already has a class, is proposed to get
one, or (for `__init__.py`) is a package export definition with no
behavior.
