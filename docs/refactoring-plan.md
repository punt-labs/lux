# Lux Refactoring Plan

**This document** is the executable refactoring plan. It combines the
OO design analysis from the class-responsibility report with the peer
review feedback into step-by-step instructions that preserve behavior
at every step. An agent executing this plan needs no other document.

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

2. **`make check` passes after every step.** This includes `make
   check-oo` (OO quality scores), lint, type check (mypy + pyright),
   and all tests green. No exceptions. OO scores must improve or
   stay the same — never regress.

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

### P.3: Fix `future_annotations` import

`apps/__init__.py` is missing `from __future__ import annotations`.
Add it. This is the only module missing the import — every other
module already has it.

**Files modified:** `src/punt_lux/apps/__init__.py` (1 line).

**Verification:** `make check-oo` — `future_annotations` metric
changes from FAIL to PASS.

### P.4: Fix `public_attr_violations` and `encapsulation_ratio`

Per-file breakdown shows 6 public attr violations in `runtime.py`
and 1 in `protocol.py`. These are `self.X = ...` assignments
without an underscore prefix.

**runtime.py (6 violations):** `RenderContext` and `CodeExecutor`
use public attrs (`self.state`, `self.dt`, `self.frame`,
`self.width`, `self.height`, `self.source`). Prefix with underscore
and add `@property` accessors where external read access is needed.

**protocol.py (1 violation):** `FrameReader` has one public attr.
Prefix with underscore.

**Files modified:** `src/punt_lux/runtime.py`, `src/punt_lux/protocol.py`.

**Verification:** `make check-oo` — `public_attr_violations` drops
to 0, `encapsulation_ratio` reaches 1.0.

### P.5: Fix `init_violations`

Per-file breakdown shows `__init__` used in:

- `display.py` (3): `TextureCache.__init__`, `WidgetState.__init__`,
  `DisplayServer.__init__`. These are non-dataclass classes.
- `display_client.py` (1): `DisplayClient.__init__`.
- `protocol.py` (1): `FrameReader.__init__`.
- `runtime.py` (2): `RenderContext.__init__`, `CodeExecutor.__init__`.

The OO scoring tool flags `__init__` on non-dataclass classes and
expects `__new__` instead. Convert each `__init__` to `__new__`
with `Self` return type, replacing `self.X = ...` with attribute
assignment on the new instance.

**Note:** This is a mechanical transformation. Each `__init__` becomes
`__new__` with `self = super().__new__(cls)` at the top and
`return self` at the bottom (if not already using that pattern).
The tool's `oo_score.py` itself uses `__new__` — follow that pattern.

**Files modified:** `src/punt_lux/display.py`,
`src/punt_lux/display_client.py`, `src/punt_lux/protocol.py`,
`src/punt_lux/runtime.py`.

**Verification:** `make check-oo` — `init_violations` drops to 0.

### P.6: Establish baseline metrics

Run `make check-oo`, `make metrics`, and `make coverage`. Record
all baselines. After pre-flight fixes P.1–P.5, the remaining
`check-oo` failures should be only the structural metrics that
require the full refactoring to fix:

- `method_ratio` (needs class extractions)
- `module_size` (needs file splits)
- `max_complexity` (needs god class decomposition)
- `classes_per_module` (needs file splits)
- `class_to_func_ratio` (needs class extractions)

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

**Class design: ElementCodec (`__init_subclass__` registration).**

The proposed `ElementCodec` replaces the 48 module-level
`_*_to_dict` / `_*_from_dict` functions and the two dispatch dicts
(`_ELEMENT_SERIALIZERS`, `_ELEMENT_DESERIALIZERS`) with a mixin that
auto-registers each element dataclass's codec pair:

- **Responsibility:** Serialize Element dataclasses to dicts and
  deserialize dicts to Elements.
- **Compositions:** None.
- **Collaborations:** Every Element dataclass (registered via
  `__init_subclass__`); `element_from_dict` / `element_to_dict`
  become module-level wrappers around the singleton.
- **Key methods:**
  - `to_dict(elem: Element) -> dict[str, Any]`
  - `from_dict(data: dict[str, Any]) -> Element`
  - `register(kind: str, cls: type, to_fn: Callable, from_fn: Callable) -> None`

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

The gain is structural, not functional. The current code works. The
free functions are repetitive but each is under 20 lines. The dispatch
dicts are already the right pattern, just spelled at module scope. The
`__init_subclass__` version eliminates the manual dict maintenance and
puts serialization next to the dataclass it serves. The real gain
comes when plugins register new element kinds --
`__init_subclass__` makes that automatic.

**Rejected alternative:** `to_dict()` / `from_dict()` as instance and
class methods directly on the dataclasses, without a mixin or registry.
This scatters the codec across 24 classes with no central dispatch.
`element_from_dict(d)` would need to inspect `d["kind"]` and then
somehow find the right class. A registry -- whether module-level dicts
or `__init_subclass__` -- is unavoidable for deserialization.

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

**Class design: MessageCodec registry.**

The proposed `MessageCodec` replaces the 95-line `message_from_dict`
if/elif chain and the 120-line `_register_serializers` closure factory
with a type-string registry.

- **Responsibility:** Serialize and deserialize Message dataclasses.
  Replace `message_to_dict`, `message_from_dict`,
  `_register_serializers`, and the `_MESSAGE_SERIALIZERS` dict.
- **Compositions:** None.
- **Collaborations:** Every Message dataclass;
  `encode_message` / `encode_frame` use `MessageCodec.to_dict`;
  `FrameReader.drain_typed` uses `MessageCodec.from_dict`.
- **Key methods:**
  - `to_dict(msg: Message) -> dict[str, Any]`
  - `from_dict(data: dict[str, Any]) -> Message`

**Concrete code -- the `_register_message` pattern:**

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

**Before** (`message_from_dict`, 95-line if/elif chain):

```python
def message_from_dict(d: dict[str, Any]) -> Message:
    msg_type = d.get("type", "")
    if msg_type == "scene":
        return _scene_from_dict(d)
    elif msg_type == "update":
        return _update_from_dict(d)
    elif msg_type == "clear":
        return ClearMessage()
    # ... 90 more lines of elif
```

**After** (registry lookup, 12 lines):

```python
def message_from_dict(d: dict[str, Any]) -> Message:
    msg_type = d.get("type", "")
    codec = _MESSAGE_CODECS.get(msg_type)
    if codec is not None:
        _, _, from_fn = codec
        return from_fn(d)
    if not isinstance(msg_type, str) or not msg_type:
        raise ValueError("Message missing or invalid 'type' field")
    return UnknownMessage(raw_type=msg_type, data=d)
```

This replaces 215 lines (95-line `message_from_dict` + 120-line
`_register_serializers`) with ~40 lines of registration plus the
same `_*_to_dict` / `_*_from_dict` functions. Net savings: ~100 lines,
plus the if/elif chain is gone.

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

**Class design:**

- **Responsibility:** Own the scene graph -- frames, scenes,
  scene-to-frame mapping, widget state per scene, and the
  update/patch pipeline. Pure state machine with no ImGui, no
  socket, no OpenGL dependency.
- **Compositions:**
  - `Frame` dataclass (promoted from `_Frame`)
  - `WidgetState` (one per scene)
- **Collaborations:**
  - `DisplayServer` -- renders scenes the manager provides
  - `SocketServer` -- receives `SceneMessage` / `UpdateMessage` /
    `ClearMessage`
  - `ElementRenderer` -- queries scene content for rendering
- **Constructor signature:**

  ```python
  def __init__(
      self,
      emit_event: EmitEventFn,
      on_scene_replaced: OnSceneReplacedFn,
  ) -> None:
  ```

  - `emit_event: EmitEventFn` -- callback for events emitted during
    `_apply_patch_set` (e.g., tree node toggle events).
  - `on_scene_replaced: OnSceneReplacedFn` -- called by
    `replace_scene_state` so DisplayServer can drain stale events
    from its own queue. SceneManager does NOT own the event queue.

- **Key method signatures:**

  ```python
  def handle_scene(self, fd: int, msg: SceneMessage) -> AckMessage: ...
  def handle_framed_scene(self, fd: int, msg: SceneMessage) -> AckMessage: ...
  def upsert_scene_in_frame(self, frame_id: str, scene_id: str, elements: list[Element]) -> None: ...
  def apply_update(self, scene_id: str, patches: list[Patch]) -> AckMessage: ...
  def resolve_scene(self, scene_id: str) -> list[Element] | None: ...
  def dismiss_scene(self, scene_id: str) -> None: ...
  def close_frame(self, frame_id: str) -> None: ...
  def clear_all(self) -> None: ...
  def current_widget_state(self, scene_id: str) -> WidgetState: ...
  ```

**Class: `Frame` (promoted from `_Frame`).**

- **Responsibility:** State for a named inner window -- owns scenes,
  tracks layout mode, cascade index, minimized state.
- The underscore prefix signals "private to this module" which is no
  longer accurate when it lives in `scene_manager.py`. This is a
  first-class domain object, not a private implementation detail.

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

**`on_scene_replaced` callback design.** `_replace_scene_state`
currently drains stale events from the event queue. SceneManager must
not own the event queue -- that stays on DisplayServer where
`_flush_events` lives. SceneManager receives
`on_scene_replaced(stale_scene_ids: list[str])`, and DisplayServer
drains its own queue. This keeps the event queue in the coordinator
where it belongs.

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

**Class design:**

- **Responsibility:** Accept, poll, read from, send to, and remove
  Unix socket client connections. The socket layer has no ImGui
  dependency. Extracting it makes IPC testable without a GPU context.
- **Compositions:**
  - `FrameReader` (one per client fd) -- buffered message framing
- **Collaborations:**
  - `DisplayServer` -- calls `poll()` each frame, receives typed
    messages
  - `protocol.encode_message` / `FrameReader.drain_typed` -- wire
    format
- **Constructor signature:**

  ```python
  def __init__(
      self,
      on_message: Callable[[socket.socket, Message], None],
      on_client_disconnected: OnClientDisconnectedFn,
      on_error: Callable[[str, str, str], None],
  ) -> None:
  ```

  - `on_message` -- callback for each deserialized message.
    DisplayServer's `_handle_message` is registered here.
  - `on_client_disconnected` -- callback when a client fd
    disconnects. DisplayServer uses this to transfer scene
    ownership. `_remove_client` currently calls into scene
    ownership transfer -- that callback replaces the direct call.
    SocketServer must not import SceneManager.
  - `on_error` -- callback for error recording (currently
    `_record_error`).

- **Key method signatures:**

  ```python
  def setup(self, socket_path: Path) -> None: ...
  def accept_connections(self) -> None: ...
  def poll_clients(self) -> list[tuple[int, Message]]: ...
  def send_to_client(self, fd: int, msg: Message) -> None: ...
  def remove_client(self, fd: int) -> None: ...
  def broadcast(self, msg: Message) -> None: ...
  ```

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

**Class design:**

- **Responsibility:** Render the `table` element kind -- filters,
  pagination, row selection, detail panel, column sizing, keyboard
  navigation, copy-to-clipboard.
- **Compositions:** None.
- **Collaborations:**
  - `ElementRenderer` -- delegates `_render_table` to this class
  - `WidgetState` -- filter state, selection state, page state
- **Constructor signature:**

  ```python
  def __init__(
      self,
      widget_state: WidgetState,
      imgui: Any,
      emit_event: EmitEventFn,
  ) -> None:
  ```

  - `widget_state` -- mutable reference, swapped by DisplayServer
    before each scene render.
  - `imgui` -- the imgui module.
  - `emit_event` -- for table row selection events.

- **Key method signatures:**

  ```python
  def render(self, table: TableElement, scene_id: str) -> None: ...
  def apply_filters(self, rows: list, filters: list[TableFilter]) -> list: ...
  def render_pagination(self, total_rows: int) -> tuple[int, int]: ...
  def render_rows(self, columns: list[str], rows: list, flags: list[str]) -> int | None: ...
  def render_detail(self, detail: TableDetail, selected_row: int) -> None: ...
  ```

**Why a class.** The 15 module-level functions all take the same
parameters: `widget_state`, `table_id`, `imgui`. This is a class
spelled as free functions. The constructor takes `widget_state` and
`imgui`; `table_id` is a method parameter (one instance serves
multiple tables in a single frame). The filter logic
(`_apply_table_filters`, `_filter_indexed_rows`, `_filter_combo`) is
pure Python and can be tested without ImGui.

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

**Class design:**

- **Responsibility:** Route `QueryRequest` messages to handler methods
  and return `QueryResponse`. Own the ring buffers for events and
  errors (for introspection only). No ImGui dependency -- fully
  unit-testable.
- **Compositions:** None.
- **Collaborations:**
  - `DisplayServer` -- registers handlers in `__init__`, receives
    query messages from socket layer
  - `SceneManager` -- many queries inspect scene state
  - `MenuManager` -- `list_menus`, `list_clients` query menu state
- **Constructor signature:**

  ```python
  def __init__(
      self,
      scene_manager: SceneManager,
      # Read accessors for client and menu state (lambdas or protocol
      # objects, not references to DisplayServer):
      get_client_names: Callable[[], dict[int, str]],
      get_client_connect_times: Callable[[], dict[int, float]],
      get_menu_registrations: Callable[[], dict[int, list[dict[str, Any]]]],
      get_agent_menus: Callable[[], list[dict[str, Any]]],
  ) -> None:
  ```

- **Key method signatures:**

  ```python
  def handle_query(self, fd: int, msg: QueryRequest) -> QueryResponse: ...
  def register_handler(self, method: str, handler: Callable) -> None: ...
  def record_event(self, event: InteractionMessage) -> None: ...
  def record_error(self, error: dict) -> None: ...
  ```

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

**Handler registration pattern.** DisplayServer registers its own
handlers during construction:

```python
self._query_dispatcher = QueryDispatcher(
    scene_manager=self._scene_manager,
    get_client_names=lambda: self._socket_server._client_names,
    get_client_connect_times=lambda: self._socket_server._client_connect_times,
    get_menu_registrations=lambda: self._menu_manager._menu_registrations,
    get_agent_menus=lambda: self._menu_manager._agent_menus,
)
self._query_dispatcher.register_handler("get_display_info", self._query_get_display_info)
self._query_dispatcher.register_handler("get_window_settings", self._query_get_window_settings)
# ... etc.
```

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

**Class design:**

- **Responsibility:** Render protocol Element dataclasses as ImGui
  widgets. One method per element kind. Dispatch by kind string via
  the existing `_RENDERERS` class variable.
- **Design pattern:** Visitor. The `_RENDERERS` dict maps element kind
  strings to method names. When a new element kind is added, one
  method is added to `ElementRenderer` and one entry to `_RENDERERS`.
  This is the Open/Closed Principle: the class is open for extension
  (new element kinds) and closed for modification (existing render
  methods don't change).
- **Compositions:** None.
- **Collaborations:**
  - `DisplayServer` / `SceneManager` -- provides elements + widget
    state
  - `WidgetState` -- reads/writes interactive widget values
  - `TextureCache` -- image rendering
  - `emit_event: Callable[[InteractionMessage], None]` -- emits
    events
- **Constructor signature (three dependencies):**

  ```python
  def __init__(
      self,
      widget_state: WidgetState,
      texture_cache: TextureCache,
      emit_event: EmitEventFn,
  ) -> None:
  ```

  - `widget_state: WidgetState` -- mutable reference, swapped by
    DisplayServer before each scene render.
  - `texture_cache: TextureCache` -- for `_render_image`.
  - `emit_event: EmitEventFn` -- for user interaction events.

  The `_RENDERERS` class variable maps kind strings to method names:

  ```python
  _RENDERERS: ClassVar[dict[str, str]] = {
      "text": "_render_text",
      "button": "_render_button",
      "separator": "_render_separator",
      # ... one entry per element kind
  }
  ```

- **Key method signatures:**

  ```python
  def render_element(self, element: Element, scene_id: str) -> None: ...
  # Plus 24 _render_* methods (one per element kind)
  ```

**Widget state handoff.** DisplayServer sets
`element_renderer.widget_state = scene_manager.current_widget_state(scene_id)`
before each scene render. This is an explicit assignment, not a shared
mutable reference threaded through layers.

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

**Class design:**

- **Responsibility:** Own all menu state -- the Lux menu, Applications
  menu, Window menu, Help menu, World panel, agent menus, and
  per-client menu registrations. Render menus. Dispatch menu-click
  events via callbacks.
- **Compositions:** None (menu items are dicts).
- **Collaborations:**
  - `DisplayServer` -- calls `render_menus()` in the ImGui callback
  - `SocketServer` -- receives `MenuMessage`, `RegisterMenuMessage`
  - `SceneManager` -- window menu items (collapse all, fit all) act
    on frames
- **Constructor signature:**

  ```python
  def __init__(
      self,
      emit_event: EmitEventFn,
      on_theme_selected: Callable[[str], None],
      on_decorated_toggled: Callable[[bool], None],
      on_opacity_changed: Callable[[float], None],
      on_font_scale_changed: Callable[[float], None],
      # Read accessors for display-wide state:
      get_themes: Callable[[], list[str]],
      get_current_theme: Callable[[], str],
      get_decorated: Callable[[], bool],
      get_opacity: Callable[[], float],
      get_font_scale: Callable[[], float],
  ) -> None:
  ```

  MenuManager receives callbacks for user selections (e.g., "user
  selected theme X", "user toggled decorated") but does not own the
  state those callbacks mutate.

- **Key method signatures:**

  ```python
  def show_menus(self, imgui_context: Any) -> None: ...
  def handle_register_menu(self, fd: int, msg: RegisterMenuMessage) -> None: ...
  def handle_menu_message(self, msg: MenuMessage) -> None: ...
  def render_world_panel(self) -> None: ...
  ```

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
state those callbacks mutate. This keeps the invariant clean:
MenuManager owns menu registrations and renders menus.

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
repeated 12-line pattern across 15 query-wrapper tools.

**Full decorator code:**

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

**Tools to migrate.** Each becomes 3-10 lines. All 15 query-wrapper
tools in their after form:

```python
@_query_tool("get_display_info")
def get_display_info() -> None:
    """Return display server metadata: backend, resolution, FPS, PID, uptime."""


@_query_tool("get_window_settings")
def get_window_settings() -> None:
    """Return current window settings (decorated, opacity, font_scale)."""


@_query_tool("get_theme")
def get_theme() -> None:
    """Return the current theme name and available themes."""


@_query_tool("list_clients")
def list_clients() -> None:
    """Return connected client info (fd, name, connect time)."""


@_query_tool("list_menus")
def list_menus() -> None:
    """Return registered menus and agent menus."""


@_query_tool("list_recent_events")
def list_recent_events(count: int = 50) -> dict[str, Any] | None:
    """Return the last N interaction events from the display."""
    return {"count": count}


@_query_tool("list_errors")
def list_errors(count: int = 50) -> dict[str, Any] | None:
    """Return the last N errors from the display."""
    return {"count": count}


@_query_tool("inspect_scene")
def inspect_scene(scene_id: str) -> dict[str, Any] | None:
    """Return the element tree for a scene."""
    return {"scene_id": scene_id}


@_query_tool("list_scenes")
def list_scenes() -> None:
    """Return all scene IDs and their frame assignments."""


@_query_tool("screenshot")
def screenshot() -> None:
    """Capture a screenshot and return the base64-encoded PNG."""


@_query_tool("set_theme")
def set_theme(theme: str) -> dict[str, Any] | None:
    """Set the display theme by name."""
    return {"theme": theme}


@_query_tool("set_window_settings")
def set_window_settings(
    decorated: bool | None = None,
    opacity: float | None = None,
    font_scale: float | None = None,
) -> dict[str, Any] | None:
    """Set window settings. All parameters are optional."""
    params: dict[str, Any] = {}
    if decorated is not None:
        params["decorated"] = decorated
    if opacity is not None:
        if not 0.3 <= opacity <= 1.0:
            raise ValueError("opacity must be between 0.3 and 1.0")
        params["opacity"] = opacity
    if font_scale is not None:
        if not 0.5 <= font_scale <= 3.0:
            raise ValueError("font_scale must be between 0.5 and 3.0")
        params["font_scale"] = font_scale
    return params


@_query_tool("set_frame_state")
def set_frame_state(
    frame_id: str,
    minimized: bool | None = None,
    layout: str | None = None,
) -> dict[str, Any] | None:
    """Set frame state (minimized, layout)."""
    params: dict[str, Any] = {"frame_id": frame_id}
    if minimized is not None:
        params["minimized"] = minimized
    if layout is not None:
        params["layout"] = layout
    return params


@_query_tool("ping")
def ping() -> None:
    """Ping the display server."""


@_query_tool("clear")
def clear() -> None:
    """Clear all scenes from the display."""
```

**`set_window_settings` edge case.** The `ValueError` raises for
invalid `opacity` or `font_scale` values happen inside the decorated
function, before the query call. The decorator's `fn(**kwargs)` call
propagates the exception to the MCP layer, which returns it as an
error response. This is correct behavior.

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
class.

**Class design:**

- **Responsibility:** Own the module-level mutable state: the cached
  `DisplayClient`, the client lock, per-session menu tracking, and
  app registration tracking.
- **Compositions:**
  - `DisplayClient` (lazily created, cached)
- **Collaborations:**
  - MCP tool functions -- all tools call `state.get_client()` instead
    of module-level `_get_client()`
  - `_lifespan` -- calls `state.get_client()` for eager connect
  - `run_mcp_session` -- calls `state.cleanup_session(key)`
- **Key method signatures:**

  ```python
  def get_client(self) -> DisplayClient: ...
  def with_reconnect(self, fn: Callable[[], T]) -> T: ...
  def cleanup_session(self, session_key: str) -> None: ...
  def setup_apps(self, client: DisplayClient) -> None: ...
  ```

- **State (moves from module level):**
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
`query()`. The deprecated wrapper pattern:

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

**Simplified `_dispatch_or_buffer`.** After deprecation, the three
`isinstance` checks for `IntrospectResponse`, `ListScenesResponse`,
and `ScreenshotResponse` in `_dispatch_or_buffer` can be removed. The
method shrinks by ~15 lines. The deprecated methods still work because
they call `query()`, which uses `_query_queue`.

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

**Class design: `ServiceBackend` (ABC):**

- **Responsibility:** Platform-specific daemon lifecycle strategy.
  Install, uninstall, and check status of the luxd service via the
  platform's service manager.
- **Compositions:** None.
- **Collaborations:** `subprocess` (launchctl / systemctl),
  `pathlib` (file I/O).

```python
from abc import ABC, abstractmethod
from pathlib import Path


class ServiceBackend(ABC):
    """Platform-specific daemon lifecycle strategy."""

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
```

**Class design: `LaunchdBackend`:**

- **Responsibility:** macOS launchd implementation.
- **State:** `_plist_dir`, `_plist_path` (constants).
- **Collaborations:** `subprocess` (launchctl), `pathlib` (file I/O).

```python
class LaunchdBackend(ServiceBackend):
    """macOS launchd implementation."""

    def __init__(self) -> None:
        self._plist_dir = Path.home() / "Library" / "LaunchAgents"
        self._plist_path = self._plist_dir / "com.punt-labs.lux.plist"

    def install(self, exec_args: list[str]) -> None: ...
    def uninstall(self) -> None: ...
    def is_active(self) -> bool: ...
    def config_path(self) -> Path:
        return self._plist_path
```

**Class design: `SystemdBackend`:**

- **Responsibility:** Linux systemd user unit implementation.
- **State:** `_unit_dir`, `_unit_path` (constants).
- **Collaborations:** `subprocess` (systemctl), `pathlib` (file I/O).

```python
class SystemdBackend(ServiceBackend):
    """Linux systemd user unit implementation."""

    def __init__(self) -> None:
        self._unit_dir = Path.home() / ".config" / "systemd" / "user"
        self._unit_path = self._unit_dir / "lux.service"

    def install(self, exec_args: list[str]) -> None: ...
    def uninstall(self) -> None: ...
    def is_active(self) -> bool: ...
    def config_path(self) -> Path:
        return self._unit_path
```

**Class design: `ServiceManager`:**

- **Responsibility:** Coordinate daemon lifecycle across platforms.
  Resolve the platform backend and delegate install / uninstall /
  restart / status operations.
- **State:** `_backend` (the resolved `ServiceBackend`).
- **Collaborations:** `ServiceBackend` (strategy), `_luxd_exec_args`
  (binary resolution).

```python
class ServiceManager:
    """Coordinate daemon lifecycle across platforms."""

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

**Shared helpers that stay module-level:**

- `_luxd_exec_args` -- binary resolution, not platform-specific.
- `detect_platform` -- returns platform string, used by
  `_resolve_backend`.
- `_has_linger` -- Linux-specific, moves to `SystemdBackend`.

**Before** (public API):

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

**After:**

```python
_manager = ServiceManager()

def install() -> str:
    return _manager.install()

def uninstall() -> str:
    return _manager.uninstall()
```

The public API functions remain as module-level wrappers for backward
compatibility. The class provides testability: inject a
`MockBackend(ServiceBackend)` that does not call `launchctl` or
`systemctl`.

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

**Class design:**

- **Responsibility:** WebSocket session multiplexer for luxd. Track
  connected MCP sessions and provide the Starlette ASGI app that
  serves them.
- **State:**
  - `_active_sessions: set[str]` -- session keys of connected clients
  - `_app: Starlette` -- the ASGI application
- **Collaborations:**
  - `tools.run_mcp_session` -- delegates MCP protocol handling
  - `uvicorn` -- HTTP/WebSocket server

```python
class SessionHub:
    """WebSocket session multiplexer for luxd."""

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

**After:**

```python
hub = SessionHub()

async def _health_route(request: Request) -> JSONResponse:
    return hub._health_route(request)

# Or more cleanly, build_app() references hub methods directly.
```

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

**Three sub-steps:**

**5.3a: Extract `DoctorChecker` to `src/punt_lux/doctor.py`.**

**Class design:**

- **Responsibility:** Run health checks against the Lux installation
  and report results. Single responsibility: collect and report
  diagnostic checks -- font availability, Python version,
  imgui-bundle, display server, Claude plugin.
- **State:** `_socket_path`, `_results: list[CheckResult]`.
- **Collaborations:** `paths.py` (display running), `shutil`
  (claude CLI).

```python
@dataclass
class CheckResult:
    """One diagnostic check result."""
    symbol: str  # _OK, _FAIL, _OPTIONAL
    message: str
    required: bool = True


class DoctorChecker:
    """Run installation health checks and collect results."""

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

Move from `__main__.py`:

- `_check_fonts` function
- `_check_plugin` function (if present)
- `_CheckFn` protocol type (eliminated -- the checker owns result
  accumulation)
- Doctor command body (100 lines -> 7 lines)
- `_OK`, `_FAIL`, `_OPTIONAL` constants
- `_PLUGIN_ID` constant

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

**After:**

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

The command body drops from 65 lines to 7.

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

**Class design:**

- **Responsibility:** Path resolution and lifecycle for a display
  server instance. Given a socket path, derive all related paths (pid
  file, log file) and manage the process lifecycle (is_running,
  cleanup, ensure, write_pid, remove_pid).
- **State:** `socket_path` (the identity of the display instance).
- **Collaborations:** `subprocess` (spawning display), `os` (process
  checks).
- **Constructor signature:**

  ```python
  def __init__(self, socket_path: Path | None = None) -> None:
      self._socket_path = socket_path or self._default_path()
  ```

- **Key method signatures:**

  ```python
  @staticmethod
  def _default_path() -> Path:
      """Resolution: $LUX_SOCKET > $XDG_RUNTIME_DIR > /tmp."""
      ...

  @property
  def socket_path(self) -> Path: ...

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

**Before** (threading socket_path everywhere):

```python
path = default_socket_path()
if is_display_running(path):
    pid = pid_file_path(path).read_text().strip()
    log = log_file_path(path)
```

**After:**

```python
display = DisplayPaths()
if display.is_running():
    pid = display.pid_path.read_text().strip()
    log = display.log_path
```

The parameter threading is eliminated. The socket path is set once
in the constructor and derived paths are properties.

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

**Class design:**

- **Responsibility:** Read and write `.punt-labs/lux.md` YAML
  frontmatter config. Own the config file path and provide typed
  read/write access to its YAML frontmatter fields.
- **State:** `_config_path` (resolved once, cached).
- **Collaborations:** `pathlib` (file I/O), `re` (frontmatter
  parsing).
- **Constructor signature:**

  ```python
  def __init__(self, config_path: Path | None = None) -> None:
      self._config_path = config_path or resolve_config_path()
  ```

- **Key method signatures:**

  ```python
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

**Before:**

```python
cfg = read_config(resolve_config_path())
write_field("display", "y", resolve_config_path())
```

**After:**

```python
config = ConfigManager()
cfg = config.read()
config.write_field("display", "y")
```

The path is resolved once in the constructor. No repeated
`resolve_config_path()` calls.

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

**Class design:**

- **Responsibility:** Atomic read/write/delete for the mcp-proxy TOML
  config file. Manage the `[lux]` section in the mcp-proxy config
  file with atomic writes and TOML serialization.
- **State:** `_path` (the config file path).
- **Collaborations:** `tomllib` (reading), `pathlib` / `os` (atomic
  write).
- **Constructor signature:**

  ```python
  def __init__(self, path: Path | None = None) -> None:
      self._path = path or (Path.home() / ".punt-labs" / "mcp-proxy" / "lux.toml")
  ```

- **Key method signatures:**

  ```python
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

**Methods (from module-level functions):**

- `read_proxy_config` -> `ProxyConfigFile.read`
- `write_proxy_config` -> `ProxyConfigFile.write`
- `delete_proxy_config` -> `ProxyConfigFile.delete`
- `_atomic_write` -> `ProxyConfigFile._atomic_write` (private)
- `_serialize_config` -> `ProxyConfigFile._serialize_config` (private
  or static)
- `_toml_escape` -> `ProxyConfigFile._toml_escape` (static)

**Before:**

```python
from punt_lux.remote import MCP_PROXY_CONFIG_PATH, write_proxy_config

write_proxy_config(url)
print(f"Wrote {MCP_PROXY_CONFIG_PATH}")
```

**After:**

```python
from punt_lux.remote import ProxyConfigFile

proxy = ProxyConfigFile()
proxy.write(url)
print(f"Wrote {proxy.path}")
```

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

**Class design:**

- **Responsibility:** Beads issue browser -- load, transform, and
  display issues. Provide the beads issue board as a self-contained
  display application.
- **State:** None persistent (stateless -- each call fetches fresh
  data).
- **Collaborations:** `subprocess` (`bd` CLI), `protocol` (Element
  types), `DisplayClient` (rendering).

```python
class BeadsBrowser:
    """Beads issue browser -- load, transform, and display issues."""

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

**Methods (from module-level functions):**

- `load_beads` -> `BeadsBrowser.load`
- `build_beads_payload` -> `BeadsBrowser.build_payload`
- `build_beads_elements` -> `BeadsBrowser.build_elements`
- `render_beads_board` -> `BeadsBrowser.render`
- `_FIELD_DEFAULTS` -> `BeadsBrowser.FIELD_DEFAULTS` (ClassVar)

**Before** (menu callback in tools.py):

```python
def _on_beads_browser(_msg: InteractionMessage) -> None:
    if _client is None:
        return
    threading.Thread(target=render_beads_board, args=(_client,), daemon=True).start()
```

**After:**

```python
_beads_browser = BeadsBrowser()

def _on_beads_browser(_msg: InteractionMessage) -> None:
    if _client is None:
        return
    threading.Thread(target=_beads_browser.render, args=(_client,), daemon=True).start()
```

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
state, no shared logic between commands (there is only one
command), and Typer provides the registration mechanism. The module is
the namespace.

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

## Event flow after extraction

The event system is the primary cross-cutting concern. Getting it
wrong creates circular dependencies. Here is the explicit flow:

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

4. **Flush**: `_flush_events()` runs once per frame. It iterates
   `_event_queue`, routes each event to the owning client's socket
   via `socket_server.send_to_client(fd, msg)`. Menu-click events
   are routed to the client that registered the menu item.

No class imports another class. All upward communication is callbacks.
Dependency flow is strictly:

```text
DisplayServer
  -> SceneManager
  -> SocketServer
  -> ElementRenderer -> (callback) -> DisplayServer
  -> MenuManager     -> (callback) -> DisplayServer
  -> QueryDispatcher -> (reads ring buffer, no callback needed)
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
