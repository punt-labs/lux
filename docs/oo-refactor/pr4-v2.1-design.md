# PR 4 v2.1 — Button + DialogElement + Observer + inbound roundtrip

**Status:** design
**Bead:** `lux-wb55`
**Plan reference:** `docs/oo-refactor/migration-plan.md` PR 4 (v2.1)
**Reference implementation:** `spikes/io_model_v1/` R3 (inbound roundtrip) and R4 (Dialog self-dismiss). Validated against `ARCHITECTURE_NOTES.md` A1–A5.
**PR 3 ancestor:** main squash `c238cf8` (lux-c2c8) — Element ABC, Renderer/Decoder/Encoder Protocols, TextElement, JsonText codec, ImGuiRendererFactory + ImGuiTextRenderer, NullRenderer + RecordingRenderer, `JsonElementFactory`/`JsonEncoderFactory`, `SceneManager._apply_patch_set` ABC branch (D6), and the `Connection` module (added; not wired into `DisplayClient` per D7) all on main.
**Worker / Evaluator:** `rmh` / `gvr`.
**Consulted:** `dna` on Element behavior shape + DialogElement contract. `mdm` on MCP tool surface. `djb` on Observer trust model. `rej` on Composite + bound-callback pattern.

## How to read this doc

This is a port doc. The spike is the design; PR 3's `pr3-v2.1-design.md` is
the working pattern; this doc maps both onto the production tree. Where the
spike or PR 3 already answers a question, this doc cites the file and section
instead of restating. The two surfaces PR 4 introduces — the Observer
subsystem inside luxd's asyncio runtime, and the hub-emit-handler dispatch —
are specified explicitly. Everything else is "lift".

Hard constraints (mission contract): (1) the 24 invariant MCP tools
registered in `src/punt_lux/tools/tools.py` keep their signatures (the
docstring there saying "29" is stale — verified count: 16 `@mcp.tool()` +
8 `@_query_tool(...)` = 24); (2) no `PublishMessage` external wire kind
(ARCHITECTURE_NOTES A3); (3) interaction-layer collapse
(`Display.interact`, `DomainPump.route_interaction`,
`domain.interaction.ButtonClicked`, `domain.event.ButtonPressed`) is OUT
OF SCOPE — PR 7 owns deletion; PR 4 lands parity gate; (4) PY-OO-2 holds
(≤ 300 lines, ≤ 3 classes per module).

## Audit note (round-2 revision)

Round-1 and round-1.x drafts named modules and classes that do not exist
on `main` HEAD (notably `protocol/updates.py`, `UpdateCodec`,
`_send_update`, a "new" `domain/events.py`). Round-2 walks every
production reference against `grep` evidence and rewrites §1, §3, §5, §6,
§7 against the verified tree. The corrections are tracked under
"Production-tree audit corrections" at the head of each affected section.

---

## Section 1 — Module layout map

### Production-tree audit corrections (round-2)

The spike modules `elements.py`, `codec.py`, `updates.py`, `hub.py` map
onto production paths that already exist (or don't). The corrections:

- **`protocol/updates.py` does not exist on `main`.** Production update
  types live in `src/punt_lux/domain/update.py`:
  `AddElement(scene_id, element, parent_id)`,
  `RemoveElement(scene_id, element_id)`,
  `SetProperty(scene_id, element_id, field, value)`. Each carries its own
  `to_dict()` / `from_dict(cls, d)` methods (PY-OO-5 compliant). There is
  no separate `UpdateCodec` class; per-class methods do the work.
- **`domain/interaction.py` already defines
  `ButtonClicked(scene_id, element_id)`.** The spike's
  `ButtonClicked(elem_id)` Event class collides with this name. PR 4
  introduces a renamed Event class — `ButtonClickEmitted` — in a new
  `domain/io_event.py` so the existing
  `domain.interaction.ButtonClicked` (which feeds the legacy
  `Display.interact` path that PR 7 owns) is left untouched.
- **`domain/interaction_event.py` exists** and holds
  `ButtonPressed(scene_id, element_id, owner_id)`. The doc previously
  said "interaction\_event.py is wrong" — that was wrong; the file is
  load-bearing for the existing `Display.interact` Event union and stays
  exactly as it is in PR 4.
- **The `src/punt_lux/hub.py` module exists** (luxd WebSocket gateway)
  and a same-name package `src/punt_lux/hub/` would shadow it on the
  import path. The PR 4 hub-emit-handler module lives in a new
  `src/punt_lux/iohub/` package; "iohub" names the io-model hub-tier
  surface (Observer + emit dispatcher) and stays distinct from the
  existing WebSocket-gateway module.

### Per-row mapping

Every spike module touched by PR 4 maps to a production destination.
Per-kind split rule follows PY-OO-2 + PR 3's `protocol/elements/<kind>.py`
convention.

| # | Spike construct | Production destination | Adaptation |
|---|---|---|---|
| 1 | `elements.py` ButtonElement (28–58) | `protocol/elements/button.py` (REWRITTEN) | Replace PR-2 dataclass with ABC subclass mirroring TextElement (§2). Keep production fields (`action`, `disabled`, `small`, `arrow`, `tooltip`) for snapshot parity. Sentinel defaults on `renderer_factory` / `emit` per D1. |
| 2 | `elements.py` DialogElement (139–185) | `protocol/elements/dialog.py` (NEW) | Grep verified: zero existing `DialogElement` in production (`ModalElement` in `layout.py:109` is a different element kind). New file, no PR-2 carcass. Mirrors §3. |
| 3 | `codec.py` JsonButtonDecoder/Encoder (44–60, 188–190) | `protocol/elements/button_codec.py` (NEW) | Per-kind codec mirroring `text_codec.py`. Field set extended to match production Button. |
| 4 | `codec.py` JsonDialogDecoder/Encoder (93–145, 209–222) | `protocol/elements/dialog_codec.py` (NEW) | Per-kind module. Bound-callback dance lifted verbatim, threading `scene_id` through DialogElement construction (§3). |
| 5 | `codec.py` `encode_interaction` / `decode_interaction` (304–309) | NOT MIGRATED in PR 4 | Production `protocol/messages/interaction.py` `InteractionMessage(element_id, action, value, scene_id, ts)` already routes through `MessageRegistry` and is load-bearing for the 8 unmigrated inputs. |
| 6 | `codec.py` `encode_button_clicked` (312–313) | `protocol/elements/button_codec.py` (added as `JsonButtonClickEmittedEncoder` class) | Spike free function becomes a small class (PY-OO-1) co-located with the Button codec. Used by the io-model hub emit dispatcher (§5). |
| 7 | `updates.py` `RemoveElement` (35–42) | already in `src/punt_lux/domain/update.py` as `RemoveElement(scene_id, element_id)` | No new file. The spike's `RemoveElement(elem_id)` shape is narrower than production's. DialogElement carries `scene_id` so its `close()` can construct the production shape (§3). |
| 8 | `updates.py` `ButtonClicked` (49–54) | `src/punt_lux/domain/io_event.py` (NEW) as `ButtonClickEmitted(element_id, action, value)` | Renamed to avoid name collision with the existing `domain.interaction.ButtonClicked` (`scene_id, element_id`). The renamed class is the io-model Event Button raises through `self._emit`; the legacy `domain.interaction.ButtonClicked` continues to feed `Display.interact` until PR 7 deletes the legacy path. |
| 9 | `hub.py` SubscriptionRegistry (132–166) | `src/punt_lux/iohub/observer.py` (NEW) | Lift adapted to asyncio per §4 (spike uses `threading.Lock` plus blocking line-socket sends; production luxd is asyncio). |
| 10 | `hub.py` hub\_emit (197–215) + handle\_display\_message (235–255) | `src/punt_lux/iohub/emit_dispatch.py` (NEW) — `HubEmitDispatcher` class | Lives alongside `tools/server.py` per-MCP-session state (constructed once per session, kept in a session-keyed dict); NOT inside `src/punt_lux/hub.py` (the WebSocket gateway is a different responsibility). |
| 11 | `hub.py` handle\_agent\_message subscribe branch (259–262) | `src/punt_lux/iohub/observer_tools.py` (NEW) + registration call from `tools/server.py` | Subscribe/unsubscribe/publish exposed as MCP tools, additive to the 24 invariant. |

**Module-size check (post-PR 4):** every new file is < 130 LoC and ≤ 3
classes (PY-OO-2 OK). `button_codec.py` (3 classes: decoder, encoder,
`ButtonClickEmitted` encoder) shares Button vocabulary so PL-CO-3 holds.
`dialog_codec.py` (2 classes), `iohub/observer.py` (1),
`iohub/emit_dispatch.py` (1), `iohub/observer_tools.py` (1),
`domain/io_event.py` (1). `domain/update.py` is **not modified** — its
`RemoveElement` already has the shape DialogElement needs.

**One-file packages.** `src/punt_lux/iohub/` is new; the existing
`src/punt_lux/hub.py` (luxd WebSocket gateway) stays unchanged at the
package root. The two names — module `hub` and package `iohub` —
coexist on the import path because the directory and file have different
basenames. Resolves PR 3's §9 Q2: a one-file package would have shadowed
the existing module; the rename to `iohub` is the only safe spelling.
`iohub/__init__.py` re-exports `HubEmitDispatcher`, `Observer`,
`WILDCARD_TOPIC`.

---

## Section 2 — ButtonElement on ABC

### Pattern source

Spike `elements.py` ButtonElement (60–106) is the template. Production
ButtonElement mirrors its `__new__`-keyword-only-injected pattern with the
fields the PR-2 dataclass already carried.

### Pre-design grep evidence

`grep -rn "ButtonElement(" src/ tests/` returns 66 lines (45 in tests, 21 in
src — mostly imports and one constructor per render test). Sentinel defaults
on `renderer_factory` and `emit` (D1) are required: without them, the 45 test
call sites of the form `ButtonElement(id="b1", label="OK")` break at
construction.

### Production ButtonElement (PR 4)

`src/punt_lux/protocol/elements/button.py` — REWRITTEN. The PR-2 dataclass
is deleted; codec body moves to `button_codec.py`; `to_dict`/`from_dict`
remain on the class as ≤ 3-line delegators per D5 (the runtime-checkable
`domain.element.Element` Protocol structurally requires both).

```python
# Module-level sentinels (per pr3-v2.1-design.md §4 D1).
_NULL_FACTORY: RendererFactory = NullRendererFactory()
def _no_emit(_msg: object) -> None: pass

class ButtonElement(Element):
    _id: str
    _label: str
    _action: str | None        # PY-TS-14 OK: None = action defaults to element id
    _disabled: bool
    _small: bool
    _arrow: str | None         # PY-TS-14 OK: None = not an arrow button
    _tooltip: str | None       # PY-TS-14 OK: absence = no tooltip
    _on_click_callback: Callable[[], None] | None
    _kind: Literal["button"]

    def __new__(cls, *,
                renderer_factory: RendererFactory = _NULL_FACTORY,
                emit: Emit = _no_emit,
                id: str, label: str, action: str | None = None,
                disabled: bool = False, small: bool = False,
                arrow: str | None = None, tooltip: str | None = None,
                on_click_callback: Callable[[], None] | None = None) -> Self:
        ...  # assign fields and return self (TextElement PR 3 pattern)

    def on_click(self) -> None:
        """Lifted from spike elements.py:98-105."""
        self._emit(ButtonClickEmitted(element_id=self._id))
        if self._on_click_callback is not None:
            self._on_click_callback()

    # @property accessors for id, kind, label, action, disabled, small,
    # arrow, tooltip.  No @property for _on_click_callback — internal
    # wiring bound at decode time (per spike R4).
    # _set_<field> setters for the patch path (D6).
    # to_dict / from_dict thin delegators to button_codec (D5).
```

### ButtonClickEmitted Event (where it lives and why renamed)

Spike's `ButtonClicked` is `updates.py:49-54` and carries `elem_id: str`
only — its wire payload (`codec.py:312-313`) is `{"elem_id": eid}`.
Production already defines `domain.interaction.ButtonClicked(scene_id,
element_id)` for the legacy `Display.interact` path (the Interaction
sum type Round-2 audit row #3). PR 4 cannot add a second class with the
same simple name in the same package without producing two
`from punt_lux.domain... import ButtonClicked` paths whose semantics
diverge — that is exactly the kind of cross-module name shadow PY-CS-7
exists to prevent.

The io-model Event is therefore named `ButtonClickEmitted` and lives in
`src/punt_lux/domain/io_event.py` (NEW). It carries the uniform parity
triple `(element_id, action="click", value=None)` so the §8 parity gate
compares it against `InteractionMessage(element_id, action, value)` by
field equality without a case-by-case adapter:

```python
@dataclass(frozen=True, slots=True)
class ButtonClickEmitted:
    element_id: str
    action: Literal["click"] = "click"        # constant for Button
    value: None = None                         # constant for Button
```

`action` and `value` are degenerate constants for the Button case — a
slider/input event class added later would carry a non-`None` `value`.
The triple shape stays uniform across event types; the parity gate
compares `(element_id, action, value)` from both paths without
case-by-case shape adapters. `ButtonClickEmitted` is the io-model Event
the ABC Button raises through `self._emit`; the existing
`domain.interaction.ButtonClicked` keeps feeding the legacy
`Display.interact` path until PR 7 deletes it.

### What's deleted from `protocol/elements/button.py`

- `@dataclass(frozen=True, slots=True)` — replaced by `__new__`.
- All dataclass fields — become `_`-prefixed slots with `@property`
  accessors.
- The codec body of `to_dict`/`from_dict` moves to `JsonButtonEncoder.encode`
  / `JsonButtonDecoder.decode` in `button_codec.py`. The methods stay as
  ≤ 3-line delegators on the class (D5).

### What stays the same

Wire shape (snapshot parity §10); `inputs.py:43` registration; the
`element_renderer.py:158` dispatch entry; `display/renderers/button_renderer.py`
(reads via @property accessors).

---

## Section 3 — DialogElement on ABC (composite + bound-callback decode)

### Pattern source

Spike `elements.py` DialogElement (139–185) plus `codec.py` JsonDialogDecoder
(93–145). Verbatim, except for threading `scene_id` through DialogElement so
its `close()` can construct the production
`RemoveElement(scene_id, element_id)` shape.

### Production-tree audit correction (round-2)

The spike's `DialogElement.close` emits `RemoveElement(elem_id=self._id)`
— a single field. Production's
`domain.update.RemoveElement(scene_id: SceneId, element_id: ElementId)`
requires both. The shape is load-bearing: `Display.apply` validates the
scene-element pair, the per-class `to_dict()` emits both fields onto the
wire, and `DomainPump._clear_scene` calls
`RemoveElement(scene_id=scene_id, element_id=element_id)` everywhere it
ships one.

**Resolution:** thread `scene_id` through DialogElement at construction
time. `JsonDialogDecoder.decode` already knows the enclosing scene id
(passed in by the per-session JsonElementFactory's enclosing decode
context); it passes that `scene_id` as a kwarg to `DialogElement(...)`,
which stores it as a `_scene_id: SceneId` slot. `close()` then builds
the production-shape `RemoveElement(scene_id=self._scene_id,
element_id=ElementId(self._id))`. This is strictly additive — no change
to `domain.update.RemoveElement`, no new "any-scene" mode, no second
sum-type branch. Alternatives rejected:

- **Extend `RemoveElement` with a "scene-implicit" mode.** Adds a `| None`
  to a frozen dataclass that every existing caller has to defensively
  handle; violates PY-TS-14 (no `| None` without contract reason).
- **Introduce a separate `RemoveSelf` Update type.** Adds a sum-type
  branch and an extra wire kind for one consumer; the discriminated
  union grows for an internal convenience. PY-OO-6 says use the
  existing type, not invent a new one.
- **Resolve `scene_id` at emit time via lookup.** Requires the emit
  dispatcher to know the inverse element → scene map. The map exists on
  `hub_display` (PR 5 territory) but does not exist in PR 4; the
  decoder-time threading is the smaller change.

### Pre-design grep evidence

`grep -rn "DialogElement(" src/ tests/` returns 0 lines. No existing
DialogElement in production. New file, no PR-2 carcass, no sentinel-default
adaptation needed. `ModalElement` in `layout.py:109` is unrelated (it is the
modal popup container; PR 4 does not touch it).

### Production DialogElement (PR 4 — NEW)

`src/punt_lux/protocol/elements/dialog.py`.

```python
class DialogElement(Element):
    _id: str
    _scene_id: SceneId          # threaded at construction (round-2)
    _children_tuple: tuple[Element, ...]
    _kind: Literal["dialog"]

    def __new__(cls, *,
                renderer_factory: RendererFactory = _NULL_FACTORY,
                emit: Emit = _no_emit,
                id: str,
                scene_id: SceneId,
                children: tuple[Element, ...] = ()) -> Self:
        ...  # assign fields, kind="dialog", return self

    def _children(self) -> tuple[Element, ...]:
        """Element ABC composite hook."""
        return self._children_tuple

    def _set_children(self, children: tuple[Element, ...]) -> None:
        """Two-pass install — JsonDialogDecoder constructs the dialog
        first (empty children), then constructs each child Button with
        on_click_callback=dialog.close bound, then calls this.  Spike R4."""
        self._children_tuple = children

    def close(self) -> None:
        """Lifted from spike elements.py:181-185 with the production
        RemoveElement(scene_id, element_id) shape (round-2 audit)."""
        self._emit(RemoveElement(
            scene_id=self._scene_id,
            element_id=ElementId(self._id),
        ))

    # @property accessors for id, kind.  to_dict / from_dict thin
    # delegators to dialog_codec (D5).
```

### Bound-callback decode (spike R4 pattern)

`src/punt_lux/protocol/elements/dialog_codec.py` — `JsonDialogDecoder.decode`
lifted from spike `codec.py:117-145`, threading `scene_id` through:

```python
def decode(self, raw: Mapping[str, object], *, scene_id: SceneId) -> DialogElement:
    dialog = DialogElement(
        renderer_factory=self._rf, emit=self._emit,
        id=str(raw["id"]), scene_id=scene_id, children=(),
    )
    children_raw = raw.get("children", [])
    children: list[Element] = []
    for c_raw in children_raw:
        if c_raw.get("kind") == "button":
            # Bind on_click_callback=dialog.close at construction so
            # the button's behavior references the dialog's API.
            children.append(ButtonElement(
                renderer_factory=self._rf, emit=self._emit,
                id=str(c_raw["id"]), label=str(c_raw["label"]),
                on_click_callback=dialog.close,
            ))
        else:
            children.append(self._factory.decode(c_raw))
    dialog._set_children(tuple(children))
    return dialog
```

Two-pass construction (build dialog with empty children → build children
with back-reference → install) is the only OO-clean way to do mutual
reference with frozen-after-construction state.

`scene_id` reaches the decoder via the `JsonElementFactory.decode` path,
which `tools/tools.py:show()` calls per-element with the enclosing
`SceneId` already in scope (the scene-id arrives as the first parameter
of `show`). PR 4 extends `JsonElementFactory.decode(raw, *, scene_id:
SceneId)` to thread the scene id through; only Dialog needs it in PR 4,
but the signature change is uniform so future composites (Window, Tab)
inherit it for free.

### Display-tier behavior

On the Display tier, `dialog.close()` exists but `self._emit` is `_no_emit`
(spike `elements.py:148-150`). PR 4 ships a minimal
`display/renderers/imgui/dialog.py` mirroring PR-2 ModalElement's ImGui
calls (distinct element, same shape). The follow-up mission decides whether
to reuse `element_renderer.py` dispatch or route through ImGuiRendererFactory
per PR 3 §2.

---

## Section 4 — Observer subsystem

### SubscriptionRegistry (production shape)

`src/punt_lux/iohub/observer.py` (NEW). Lifted from spike `hub.py:132-166`,
adapted to asyncio. See §6 for the inbound dispatch flow that uses
`loop.call_soon_threadsafe` to schedule publish on the hub's event loop
from the thread-side listener.

```python
class Observer:
    """Hub-side topic → connection-id registry; cascade-on-disconnect.
    Adapted from spike SubscriptionRegistry to asyncio (see §11 Q1)."""

    _by_topic: dict[str, set[str]]            # topic → {connection_id}
    _lock: asyncio.Lock
    _push: PushFn                              # (cid, payload) → awaitable

    def __new__(cls, *, push: PushFn) -> Self: ...

    async def subscribe(self, topic: str, cid: str) -> None: ...
    async def unsubscribe(self, topic: str, cid: str) -> None: ...
    async def remove_connection(self, cid: str) -> None: ...
    async def publish(self, topic: str, payload: dict[str, object]) -> int:
        """Fan out 'observed' envelope to every exact-topic subscriber AND
        every wildcard subscriber whose pattern matches `topic`.  Per
        ARCHITECTURE_NOTES A4: in-process call, wire-output effect."""
```

### Wildcard subscriptions (`WILDCARD_TOPIC`)

The spike has no recv-equivalent (`agent.py:48-60` registers one
exact-match `handle` per topic). Production's load-bearing
`DisplayClient.recv()` shim (§7) cannot enumerate `interaction.<id>`
topics ahead of time — element ids are unknown until publish. Observer
therefore admits one sentinel topic `WILDCARD_TOPIC = "*"` that matches
every published topic; registry-local, no wire change:

```python
WILDCARD_TOPIC: Final = "*"

async def publish(self, topic: str, payload: dict[str, object]) -> int:
    async with self._lock:
        targets = set(self._by_topic.get(topic, ())) \
                | set(self._by_topic.get(WILDCARD_TOPIC, ()))
    for cid in targets:
        await self._push(cid, {"kind": "observed",
                                "topic": topic, "payload": payload})
    return len(targets)
```

Set-union dedupes a cid subscribed to both `interaction.btn1` and
`WILDCARD_TOPIC`. Wildcard is reserved for the polling-shim adapter; the
MCP `subscribe` tool rejects `"*"` so agents must use exact-match topics.

`PushFn` type alias: `Callable[[str, dict[str, object]], Awaitable[None]]`.
The registry is injected with whatever push channel the surrounding context
exposes — for production, the per-MCP-session writer that ships an
`observed` envelope back through the existing `MessageRegistry` wire path
(D7 resolution: reuse the existing length-prefixed `InteractionMessage`
channel shape; a new `ObservedMessage` only if `MessageRegistry` proves
inadequate — see Open Question 2). The registry knows nothing about
sockets, so it tests with a `RecordingPush` fixture (PY-DP-9 Null Object).

### Hub-internal API

`hub.subscribe(cid, topic)`, `hub.unsubscribe(cid, topic)`,
`hub.publish(topic, payload)` are thin methods on whatever owns the
Observer instance per session. The current `tools/server.py` per-session
state already exists: a `_session_key: ContextVar[str]` (line 108) plus
a `_session_menus: dict[str, list[str]]` registry (line 111). The
Observer joins that state via a new module-level
`_session_observers: dict[str, Observer]` populated in `run_mcp_session`
(line 133). The session owner exposes
`subscribe`/`unsubscribe`/`publish` to internal callers (the emit
dispatcher in §5) AND wires the MCP tools below.

### MCP tool surface (additive)

`src/punt_lux/iohub/observer_tools.py` (NEW). Three FastMCP tools,
registered in `tools/server.py` alongside the 24 invariant tools:

```python
class ObserverTools:
    """Holds a per-session Observer; registers three MCP tools.  Lifts
    spike's agent socket handler (hub.py:257-299) into MCP."""

    _observer: Observer
    _connection_id: str

    def register(self, mcp: FastMCP) -> None:
        @mcp.tool
        async def subscribe(topic: str) -> dict[str, object]: ...
        @mcp.tool
        async def unsubscribe(topic: str) -> dict[str, object]: ...
        @mcp.tool
        async def publish(topic: str,
                          payload: dict[str, object]) -> dict[str, object]: ...
```

`connection_id` derives from `_session_key.get()` (the same ContextVar
the existing per-session state keys on, line 108 of `tools/server.py`).
Subscribe/unsubscribe register/remove `(topic, connection_id)`. Publish
fans out via `Observer.publish`.

### Trust model

Per djb consultation: any agent can subscribe to any topic; any agent can
publish on any topic. No ACLs in PR 4. The model is trusted multi-tenant on
a single host — luxd binds to 127.0.0.1, CSWSH Origin allowlist already gates
browsers (`hub.py:74-78`). The implementation commit (ii) lands a small
"Trust model" subsection in `docs/architecture/io-model.md`. Later PR can add
per-topic ACLs if needed.

### Cascade on disconnect

When a WebSocket session closes, `tools/server.py:_cleanup_session(session_key)`
(line 114) already runs in the `run_mcp_session` `finally:` block (line
164). PR 4 extends `_cleanup_session` to schedule
`observer.remove_connection(cid)` on the event loop (the session is
running on the loop at cleanup time, so `await` is direct). The
session-level lifecycle is the right hook — Observer never owns the
disconnect signal directly.

---

## Section 5 — Hub emit-handler dispatch

### Production-tree audit corrections (round-2)

Round-1 drafts named `UpdateCodec` and `_send_update` that do not exist.
The verified production references:

- **No `UpdateCodec` class.** `AddElement`, `RemoveElement`,
  `SetProperty` carry their own `to_dict()` methods. The "update encode"
  call is `update.to_dict()` directly.
- **No `_send_update` method on `DisplayClient`.** The lowest-level send
  is `DisplayClient._send(msg: Message)` (line 378) which takes a
  `Message` dataclass, encodes it via `encode_message`, and writes the
  framed bytes under `self._lock`. The session-owning code dispatches
  via this method, wrapping the domain Update in an `UpdateMessage` (the
  wire transport for incremental scene updates, defined in
  `protocol/messages/scene.py:43`).
- **For PR 4, only `RemoveElement` flows through the dispatcher in the
  Update branch** (Dialog.close is the only emitter). `AddElement` is
  agent-initiated, not behavior-initiated, and ships through the
  existing `show()` path — PR 4 does not add a second
  `AddElement`-from-emit path. The dispatcher's Update branch is
  therefore single-case in PR 4; PR 5 widens it when `SetProperty` from
  behavior lands.

### Pattern source

Spike `hub.py:197-215` `hub_emit`. Per ARCHITECTURE\_NOTES A2: the emit
handler is the single fan-out point for everything an Element behavior
raises through `self._emit`. Two branches: Events → publish; Updates →
accept + ship.

### Production shape

`src/punt_lux/iohub/emit_dispatch.py` — `HubEmitDispatcher`.

```python
class HubEmitDispatcher:
    """Satisfies the Emit Protocol.  JsonElementFactory passes
    `dispatcher.dispatch` as every ABC Element's `emit` channel."""

    _observer: Observer
    _send: SendMessageFn             # DisplayClient._send bound for this session
    _loop: asyncio.AbstractEventLoop  # captured at construction; see §6

    def __new__(cls, *,
                observer: Observer,
                send: SendMessageFn,
                loop: asyncio.AbstractEventLoop) -> Self: ...

    def dispatch(self, message: object) -> None:
        """Routes by type per A2."""
        match message:
            case ButtonClickEmitted():
                topic = f"interaction.{message.element_id}"
                payload = JsonButtonClickEmittedEncoder().encode(message)
                # See §6: publish must run on the hub's event loop because
                # Observer's lock is asyncio.Lock and _push is awaitable.
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(
                        self._observer.publish(topic, payload),
                    ),
                )
            case RemoveElement():
                # PR 4 ships the dispatch; full hub_display.accept lands
                # in PR 5.  See §11 Q3.  The wire envelope for a single
                # remove is the existing UpdateMessage shape — PR 5
                # generalizes when SetProperty joins the emit-Update set.
                self._send(_remove_to_update_message(message))
            case _:
                msg = f"Unknown message: {type(message).__name__}"
                raise ValueError(msg)
```

`SendMessageFn` type alias: `Callable[[Message], None]` — exactly
`DisplayClient._send`'s signature.

`_remove_to_update_message(remove: RemoveElement) -> UpdateMessage`
wraps the domain `RemoveElement` into the wire `UpdateMessage(scene_id,
patches=[...])` envelope. PR 4 ships this conversion as a small free
helper inside `iohub/emit_dispatch.py` (single-call-site, single
emitter, ≤ 5 LoC); PR 5 promotes it to a method on a `HubDisplay`-side
encoder when SetProperty joins the set. The decision to keep it a free
helper now and absorb it later follows PY-OO-7: don't ship a class
without a second method.

The `dispatch` method satisfies the `Emit` Protocol from
`protocol/renderer.py:17` (`type Emit = Callable[[object], None]`).
Synchronous wrapper around async work — `call_soon_threadsafe` is the
asyncio API for scheduling work from a non-loop thread (see §6 for why
this matters). Behavior methods on Elements stay synchronous (per spike:
`def on_click(self) -> None`, not `async def`) so the synchronous emit
signature is the right contract.

### Where it plugs in

The session-owning code in `tools/server.py:run_mcp_session` constructs:

1. The Observer (per-session; push wraps the per-session writer that
   ships `observed` envelopes through the existing wire — §6, §11 Q2).
2. The HubEmitDispatcher (`observer`, `send=client._send`,
   `loop=asyncio.get_running_loop()` — the loop is captured at
   construction so the dispatcher can schedule async work even when
   `dispatch` fires from the listener thread).
3. The JsonElementFactory (`renderer_factory=NullRendererFactory()`,
   `emit=dispatcher.dispatch`) — so every ABC Element decoded from the
   wire gets the dispatcher as its emit channel.

The session-keyed factories live in
`_session_factories: dict[str, JsonElementFactory]` (NEW
module-level dict in `tools/server.py`, mirroring `_session_menus` at
line 111). `tools/tools.py:show()` reads
`_session_factories[_session_key.get()]` to look up the per-session
factory without changing its function signature — the ContextVar
pattern already in place is the integration path. PR 4 adds `kind ==
"button"` and `kind == "dialog"` cases inside `JsonElementFactory.decode`
routing through that factory (D2 follow-up; Text already routes per
PR 3).

---

## Section 6 — First Observer consumer (`interaction.<id>` push — PY-RF-2)

### Production-tree audit corrections (round-2)

Round-1 drafts proposed `asyncio.create_task` for the inbound publish
hop. That is wrong:
`DisplayClient._listener_loop` (line 309) is a `threading.Thread` target;
the listener decodes inbound `InteractionMessage` on a worker thread,
not in the asyncio event loop. Calling `asyncio.create_task` from a
non-loop thread raises `RuntimeError: no running event loop`.

The correct hand-off is `loop.call_soon_threadsafe(...)`, scheduling the
publish coroutine on the hub's event loop (captured at dispatcher
construction time — see §5's `_loop` slot). This is the asyncio API
designed exactly for "thread produces work, event loop consumes it".

### Pattern source

Spike `hub.py:235-255` `handle_display_message`: on inbound
`InteractionMessage`, decode → resolve on `hub_display` → if Button +
click, call `elem.on_click()` → emit `ButtonClickEmitted` → publish
`interaction.<id>` → subscribers receive `observed(topic, payload)`.

### Production shape

The existing `tools/server.py` MCP session receives display-side
`InteractionMessage` via the existing `DisplayClient._listener_loop` →
`_dispatch_or_buffer` → callback path (`display_client.py:309-368`). PR 4
adds a parallel hub-side flow for Button clicks. When the listener
routes an `InteractionMessage(element_id=X, action="click")`:

- **Legacy path** (unchanged): `_dispatch_or_buffer` looks up
  `self._callbacks.get((element_id, action))`; if registered, the
  callback fires on the listener thread. Load-bearing for the 8
  unmigrated inputs and for any agent that called `client.on_event()`.
  PR 4 does NOT remove this.
- **New path (guarded — see Click-value guard below):** the per-session
  ABC ButtonElement registry (if X resolves to a Button on the hub-side
  `hub_display` mirror AND the wire `value` shape is the boolean `True`)
  invokes `elem.on_click()`, which raises `ButtonClickEmitted` through
  `self._emit` → `HubEmitDispatcher.dispatch`. Because dispatch runs on
  the listener thread, the dispatcher uses `loop.call_soon_threadsafe`
  to schedule `Observer.publish("interaction.X", {...})` on the hub's
  event loop. The publish then fans out to subscribers via the asyncio
  `_push` channel.

### Click-value guard (kind AND value shape)

Resolution-by-element-id is necessary but NOT sufficient. The hub-side
branch above MUST replicate the production
`DomainPump._is_button_click(msg, elem)` predicate
(`src/punt_lux/display/domain_pump.py:170-190`) exactly: a click fires
`on_click()` if and only if BOTH conditions hold —

1. The resolved element is a Button (`elem.kind == "button"`, i.e.
   `isinstance(elem, ButtonElement)` on the hub-side mirror).
2. The wire `value` is the boolean `True` (`msg.value is True`, by
   identity not truthiness — `1`, `"True"`, a non-empty dict are all
   distinct from boolean `True`).

Without the second guard, a non-click `InteractionMessage` whose
`element_id` happens to collide with a button in the scene would
silently fire `on_click()`. PR #187 Bugbot HIGH named the menu-id case:
menu payloads ship `value={...}` (a dict), not `True`; a menu id
identical to a button id would have fired a phantom `ButtonPressed` to
subscribers. The fix landed for `DomainPump.route_interaction` in
production; the hub-side new path MUST carry the same predicate so the
io-model surface inherits the same protection rather than reopening the
defect class. Cite `domain_pump.py:170-190` in code comments; tests
named in §10 ("Click guard rejects non-True value shapes") assert the
predicate behavior.

For PR 4 the "hub-side `hub_display`" mirror lives inside the
session-owning code as a `dict[str, Element]` indexed when `show()`
builds the Element tree (per spike `hub.py:91-99`
`HubDisplay._index`). PR 5 promotes this to a proper HubDisplay
class. PR 4 ships the minimal indexed dict; the structure is the spike's
`HubDisplay._by_id` minus the SetProperty branch (PR 5 owns).

### The load-bearing consumer

`interaction.<id>` IS the first real consumer of the Observer subsystem.
There is no manufactured `scene.accepted` or similar — `interaction.<id>` is
what agents need to react to clicks per spike R3/R4. This satisfies PY-RF-2:
the Observer is wired into a real call path the same commit it ships, not
"create now, wire later".

---

## Section 7 — `recv()` polling shim (deprecated for PR 12)

### Production-tree audit corrections (round-2)

Round-1.x drafts proposed `asyncio.Queue` + an awaited `recv()`. Verified
production shape (`display_client.py:565-583`):

```python
def recv(self, timeout: float | None = None) -> Message | None:
    """Receive the next message from the display.

    Thread-safe.  When the listener is active, blocks on the
    ``_pending`` queue.  When inactive, reads directly from the
    socket.  Returns ``None`` on timeout.
    """
    t = timeout if timeout is not None else self._recv_timeout
    if self.listener_active:
        try:
            return self._pending.get(timeout=t)
        except queue.Empty:
            return None
    ...
```

`recv()` is fully synchronous: signature `Message | None`, returns from
`queue.SimpleQueue.get(timeout=t)`, raises nothing
async-flavoured. `_pending` is a `queue.SimpleQueue[Message]` (line 95);
every consumer downstream — including the MCP `recv` tool in
`tools/tools.py:777` — assumes a blocking, thread-safe queue.

The shim must therefore use a `queue.SimpleQueue` (or `queue.Queue`),
NOT `asyncio.Queue`. The asyncio side of the world (Observer fan-out,
event-loop scheduling) lives behind the dispatcher and does not surface
through `recv()`. Migrating `recv()` to async is a separate concern with
a long blast radius (every caller would change); PR 4 does not attempt
it.

### Existing shape

`DisplayClient.recv()` returns the next message from a `_pending`
queue, populated by the listener thread when it sees a message with no
registered callback. Tests and agents that pre-date the Observer call
`recv()` to block until the next `InteractionMessage`.

### PR 4 reimplementation

`recv()` is reimplemented as a polling adapter over the per-session
Observer using the wildcard subscription form specified in §4. The shim
crosses the thread / event-loop boundary in the opposite direction from
§6:

1. Subscribe a synthetic cid (`recv-shim-<session>`) to `WILDCARD_TOPIC`.
   The Observer-side `_push` callback for this cid is an async function
   that reconstructs an `InteractionMessage` from the published payload
   and calls `self._pending.put(msg)` — i.e. it writes into the
   existing `DisplayClient._pending` queue (`queue.SimpleQueue[Message]`,
   line 95). There is no separate "shim queue" — the shim and the
   listener thread share `_pending`. Naming a second queue would imply
   two stores to drain; only one exists.
2. Inbound `InteractionMessage` follows the §6 hub-side path (resolve →
   `on_click` → `ButtonClickEmitted` → dispatcher →
   `loop.call_soon_threadsafe` → `Observer.publish`).
3. The wildcard branch fires the shim's async `_push`, which appends to
   `_pending`.
4. `DisplayClient.recv()` reads `self._pending.get(timeout=t)` — the
   same blocking call it has always made. PR 4 adds a second producer
   to `_pending` (the wildcard `_push` writing from the asyncio loop)
   alongside the existing listener-thread producer for non-interaction
   messages. Existing callers see the same `InteractionMessage` shape
   as before.

The shim adapter owns the producer-side wiring (subscribe, decode the
`observed` envelope back into an `InteractionMessage`, hand to
`_pending`); `Observer` itself only fans out push calls (§4 invariant:
it knows nothing about buffering). `queue.SimpleQueue.put` is safe from
both an async coroutine (running on the loop) and a thread; no
synchronisation primitive needed. Tests verify `recv()` returns the
same shape it did pre-PR-4 (snapshot fixture in commit (v)).

### Deprecation note

`DisplayClient.recv()` gets a deprecation docstring directing callers to
subscribe to the typed `interaction.<id>` topic per agent and consume via
the listener callback path. The polling shim deletes in PR 12 once every
consumer has migrated; it stays load-bearing through PRs 5–11.

---

## Section 8 — Interaction trace parity gate

### What it asserts

Per migration-plan PR 4 row 218 commit (vii): a regression test records
`(element_id, action, value)` triples produced by:

1. The PR-2 baseline path (`Display.interact` → `DomainPump.route_interaction`
   → `ButtonPressed` → legacy `InteractionMessage` on the wire).
2. The new io-model path (display detects click → `InteractionMessage` on
   the wire → hub-side ABC ButtonElement → `on_click` →
   `ButtonClickEmitted` Event → Observer publish).

Both paths produce the same triple shape because `ButtonClickEmitted`
carries the same `(element_id, action, value)` fields as
`InteractionMessage` per §2 — for Button clicks the triple is always
`(<button_id>, "click", None)` from `ButtonClickEmitted` and
`(<button_id>, "click", True)` from `InteractionMessage` (the legacy
wire carries `value=True` per `domain_pump.py:184`); the parity
assertion normalises both to `(<button_id>, "click")` and compares the
two-tuple. The parity gate is therefore field-level equality on the same
positional shape, not a cross-type adapter.

The test asserts the two paths produce equivalent traces for Button
clicks. This is the load-bearing proof that PR 4 has not broken the
legacy path AND that PR 7's deletion of the legacy path is safe.

### Implementation

`tests/regression/test_interaction_trace_parity.py` (NEW). The test:

1. Sets up a Display with a Button via `DisplayClient.show(...)`.
2. Records the legacy trace: triggers the click via the existing test
   harness (`InteractionMessage` synthesized into the display); captures
   what the listener dispatches.
3. Records the new trace: same click event, but observed via a subscribed
   `interaction.<id>` topic.
4. Asserts the recorded triples match by `(element_id, action)` (value is
   `True` on the wire, `None` on the io-model side — the parity assertion
   normalises both to "click happened").

Existing tests in `tests/test_inputs_migration.py` use the legacy path; the
parity test reuses those fixtures plus a new Observer fixture.

---

## Section 9 — Internal commit sequence

Seven commits per migration-plan.md PR 4 row 218. Each commit passes
`make check` + `make snapshot-parity` + local code-reviewer +
silent-failure-hunter + OO ratchet.

### (i) ButtonElement on ABC + JsonButtonDecoder/Encoder + headless behavior test

- **Create:** `protocol/elements/button_codec.py` (`JsonButtonDecoder`,
  `JsonButtonEncoder`, `JsonButtonClickEmittedEncoder`).
- **Create:** `domain/io_event.py` — `ButtonClickEmitted` frozen
  dataclass per §2.
- **Modify:** `protocol/elements/button.py` — REWRITE per §2 (delete
  dataclass; add ABC subclass with sentinel defaults D1; thin
  `to_dict`/`from_dict` delegators D5; `on_click` plus
  `_on_click_callback`; setters D6).
- **Modify:** `protocol/elements/__init__.py` — add `kind == "button"`
  route through `JsonElementFactory`; keep `_codec` fallback for the
  other 22 unmigrated kinds.
- **Modify:** `protocol/elements/inputs.py:43` — `register("button",
  ButtonElement, ButtonElement.to_dict, ButtonElement.from_dict)` keeps
  working because the delegators are still on the class.
- **Tests:** `test_button_recording.py` (RecordingRenderer shape),
  `test_button_codec.py` (wire roundtrip, all field combinations),
  `test_button_on_click.py` (emits `ButtonClickEmitted`; bound callback
  fires; uses `RecordingEmit` list-append per PR 3 pattern).
- **PY-RF-2 consumer:** `test_button_on_click.py`. Snapshot parity holds.

### (ii) Observer + emit dispatcher + unit tests

- **Create:** `iohub/__init__.py` with
  `__all__ = ["HubEmitDispatcher", "Observer", "WILDCARD_TOPIC"]`.
- **Create:** `iohub/observer.py` — Observer class per §4.
- **Create:** `iohub/emit_dispatch.py` — `HubEmitDispatcher` per §5,
  including the `_remove_to_update_message` helper.
- **Tests:** `test_observer.py` (subscribe/unsubscribe/publish fan-out
  with `RecordingPush`; cascade-on-disconnect),
  `test_emit_dispatch.py` (`ButtonClickEmitted` → publish,
  `RemoveElement` → encode + send, unknown → `ValueError`; thread →
  loop hand-off verified with an `asyncio.run_coroutine_threadsafe`
  shape-check).
- **Doc patch:** "Trust model" subsection in
  `docs/architecture/io-model.md` per §4.
- **PY-RF-2 consumer:** dispatch test consumes Observer.

### (iii) MCP subscribe/unsubscribe/publish tools + server-push integration test

- **Create:** `iohub/observer_tools.py` — `ObserverTools.register(mcp)`
  per §4.
- **Modify:** `tools/server.py` — add `_session_factories: dict[str,
  JsonElementFactory]` and `_session_observers: dict[str, Observer]`
  (mirroring `_session_menus` at line 111); instantiate per-session
  Observer + dispatcher + factory in `run_mcp_session` (line 133);
  register `ObserverTools` alongside the 24 invariant tool registrations;
  extend `_cleanup_session` (line 114) to schedule
  `observer.remove_connection(session_key)` on the event loop.
- **Tests:** `test_observer_mcp.py` — connect test MCP client; subscribe,
  publish; assert `observed(topic, payload)` push received (Starlette
  TestClient + WebSocket per existing harness pattern).
- **PY-RF-2 consumer:** the integration test.

### (iv) DialogElement + JsonDialogDecoder (bound-callback) + JsonDialogEncoder + headless dismiss test

- **Create:** `protocol/elements/dialog.py` per §3.
- **Create:** `protocol/elements/dialog_codec.py` per §3.
- **Modify:** `protocol/element_factory.py` — `JsonElementFactory.decode`
  takes a `scene_id: SceneId` kwarg and threads it through to
  per-kind decoders that need it (Dialog); existing Text branch
  ignores it (TextElement does not need scene_id).
- **Modify:** `protocol/elements/__init__.py` — `element_from_dict`
  threads `scene_id` through (callers in PR 4: `show()`, scene
  ingestion in SceneManager); add `kind == "dialog"` route through
  JsonElementFactory; add `DialogElement` to the `Element` union;
  re-export.
- **Modify:** `display/element_renderer.py` — add `(DialogElement,
  "_dialog_renderer")` dispatch entry pointing to the new
  `display/renderers/imgui/dialog.py`.
- **Create:** `display/renderers/imgui/dialog.py` — minimal ImGui dialog
  renderer (per §3 last paragraph).
- **Tests:** `test_dialog_close.py` (emits `RemoveElement(scene_id=...,
  element_id=...)` with both fields populated from the threaded scene
  id), `test_dialog_codec.py` (wire roundtrip; bound-callback: decode a
  wire dict with two child Buttons; assert each child's
  `_on_click_callback is dialog.close`),
  `test_dialog_recording.py` (composite walk).
- **PY-RF-2 consumer:** `test_dialog_codec.py` (bound-callback).

### (v) Hub publishes `interaction.<id>` on routed InteractionMessage + `recv()` polling shim + end-to-end test

- **Modify:** `tools/server.py` — extend the per-session state with the
  hub-side `_hub_display_index: dict[str, dict[str, Element]]`
  (session_key → element_id → Element). `show()` populates the index
  when it builds the Element tree.
- **Modify:** `display_client.py` (`_dispatch_or_buffer`,
  `_listener_loop` integration) — when an `InteractionMessage` arrives
  AND `element_id` resolves to a Button on the per-session
  `_hub_display_index`, invoke `elem.on_click()` (the dispatcher does
  the rest per §5 / §6).
- **Modify:** wire the polling-shim path per §7 — subscribe a
  `recv-shim-<session>` cid to `WILDCARD_TOPIC` and have its `_push`
  enqueue onto the existing `_pending` queue.
- **Tests:** `test_button_inbound_e2e.py` (display click →
  `InteractionMessage` → hub resolve → `on_click` → publish → agent
  push, AND `test_click_guard_rejects_non_true_value` per §6 click
  guard: parameterise over `value` shapes `{...}` / `1` / `"True"` /
  `None` and assert `on_click()` does NOT fire even when `element_id`
  matches a button), `test_recv_polling_shim.py` (pre-PR-4 `recv()`
  callers still receive the same `InteractionMessage` shape).
- **PY-RF-2 consumer:** the e2e test.

### (vi) End-to-end DialogElement test (R4 ported)

- **No source changes** — dispatch from (v) + Dialog from (iv) compose.
- **Tests:** `test_dialog_self_dismiss.py` — `Dialog{Label, Button(Yes),
  Button(No)}`; agent subscribes `interaction.btn_yes`/`btn_no`; click
  Yes; assert `RemoveElement(scene_id=..., element_id=...)` sent AND
  `interaction.btn_yes` push received.
- **PY-RF-2 consumer:** the e2e test consumes (i)–(v).

### (vii) Interaction trace parity gate

- **No source changes.**
- **Tests:** `test_interaction_trace_parity.py` per §8.
- **PY-RF-2 consumer:** the parity test.

### Per-commit gates

- `make check` — exit 0.
- `make snapshot-parity` — Button wire bytes identical to PR-2 (Dialog is
  new; no PR-2 baseline to compare). Acceptance §10.
- `feature-dev:code-reviewer` + `pr-review-toolkit:silent-failure-hunter`
  zero findings.
- OO ratchet (`.oo-baseline.json`) holds or improves on each touched file.

---

## Section 10 — Acceptance verification map

Per migration-plan.md PR 4 row 223:

| Criterion | Verifying test / command |
|---|---|
| `make snapshot-parity` passes for Button wire bytes | Replays PR-0 characterization snapshots for `show()` calls containing Button; byte-compares serialized SceneMessage. ABC field set matches PR-2; encoder omit-when-default rules preserved. |
| End-to-end Button click → subscribed agent push works | `tests/integration/test_button_inbound_e2e.py::test_click_emits_observed_push`. |
| Dialog self-dismiss works end-to-end | `tests/integration/test_dialog_self_dismiss.py::test_click_yes_dismisses_dialog_and_pushes_observed`. |
| Interaction trace parity passes for Button | `tests/regression/test_interaction_trace_parity.py::test_legacy_and_io_model_traces_match`. |
| Click guard rejects non-True value shapes (PR #187 Bugbot HIGH precedent) | `tests/integration/test_button_inbound_e2e.py::test_click_guard_rejects_non_true_value` — asserts `on_click()` does NOT fire for `InteractionMessage(action="click", value={...})` (menu payload), `value=1`, `value="True"`, or `value=None` even when `element_id` resolves to a Button. Mirrors `domain_pump.py:170-190` `_is_button_click` predicate. |
| `recv()` polling shim works (existing agents unbroken) | `tests/integration/test_recv_polling_shim.py::test_recv_returns_interaction_message_via_observer`. |
| `make check` clean | OO ratchet, mypy/pyright, ruff format + lint, radon CC, pylint design. |
| Zero `to_dict`/`from_dict` on ButtonElement beyond delegators (D5) | `grep -A 4 "def to_dict\|def from_dict" src/punt_lux/protocol/elements/button.py` shows ≤ 3 lines per body delegating to JsonButtonEncoder/Decoder. |
| Zero `to_dict`/`from_dict` on DialogElement beyond delegators (D5) | Same grep on `dialog.py`. |
| All 24 invariant MCP tools continue to work | `grep -c "@mcp.tool()" src/punt_lux/tools/tools.py` returns 16; `grep -c "@_query_tool" src/punt_lux/tools/tools.py` returns 8; total 24, same as main. |
| 3 new Observer tools registered and additive | `grep -n "subscribe\|unsubscribe\|publish" src/punt_lux/iohub/observer_tools.py` shows three tool definitions; integration test §9 (iii) verifies wire behavior. |
| `JsonElementFactory` routes Button + Dialog (D2 follow-up) | `grep -n 'kind == .button.\|kind == .dialog.' src/punt_lux/protocol/element_factory.py` returns exactly two lines. |
| Observer cascade-on-disconnect works | `tests/domain/test_observer.py::test_remove_connection_clears_all_topics`. |
| No `PublishMessage` wire kind | `grep -rn "PublishMessage" src/` returns zero. |
| No interaction-layer deletion | `grep -n "class ButtonPressed\|def route_interaction\|def interact" src/` returns the same lines as main (PR 7 owns deletion). |
| `domain.interaction.ButtonClicked` unchanged | `grep -n "class ButtonClicked" src/punt_lux/domain/interaction.py` returns line 27 with `(scene_id, element_id)` shape — io-model uses the renamed `ButtonClickEmitted` to avoid collision. |
| `domain.update.RemoveElement` unchanged | `grep -n "class RemoveElement" src/punt_lux/domain/update.py` returns line 74 with `(scene_id, element_id)` shape — DialogElement threads `scene_id` at construction to construct it. |

13 new test files across `tests/render/`, `tests/protocol/`,
`tests/domain/`, `tests/iohub/`, `tests/integration/`, `tests/regression/`
— each named in §9 commit (i)–(vii). Create `tests/iohub/` and
`tests/regression/` with empty `__init__.py` per existing pattern.

---

## Section 11 — Open questions for gvr / operator

Questions the spike and PR 3 pattern do not answer. Each needs an
explicit ruling before implementation.

### 1. SubscriptionRegistry concurrency primitive

Spike uses `threading.Lock` plus blocking send inside the lock
(`hub.py:154-166`). Production luxd is asyncio; §4 proposes `asyncio.Lock`
plus awaitable `PushFn`; alternative is snapshot-under-short-lock then
iterate outside. The thread-to-loop hand-off in §6 (via
`call_soon_threadsafe`) is independent of this choice — both options
work behind the same dispatcher. **Question:** `asyncio.Lock` (per §4)
or snapshot-then-iterate (per spike)? Matters when subscribe/unsubscribe
races mid-publish.

### 2. Observer push wire path

Spike sends `{kind: observed, topic, payload}` over the agent socket
(`hub.py:162`). Production candidates:

**(a)** Add `ObservedMessage(topic, payload)` to `MessageRegistry`; ship
on the existing wire. Pro: zero new transport. Con: registers a
logically different layer in the same dispatcher.

**(b)** Reuse `InteractionMessage` as carrier; `publish` for
`interaction.<id>` synthesizes one from the hub. Pro: zero new wire
types. Con: only works for `interaction.*` topics.

D7 said "reuse the existing wire"; §4/§6 propose (a); (b) is the
minimum-delta option. **Question:** (a) or (b)? djb's trust input
applies if (a) lands.

### 3. Hub-side HubDisplay mirror

§6 proposes a minimal `dict[str, Element]` in the session-owning code so
PR 4's resolve path works (`_hub_display_index` per §9 commit (v)). The
spike's full `HubDisplay` class (`hub.py:49-123`) ships its `accept`
branch in PR 5. **Question:** minimal dict in PR 4 (recommended), or
full `HubDisplay` class now (saves PR 5 wiring; adds untested code)?

### 4. Trust model documentation patch

§4 lands a "Trust model" subsection in `docs/architecture/io-model.md`.
**Question:** OK to land in commit (ii) (recommended), or separate doc
PR?

### 5. `scene_id` threading through `JsonElementFactory.decode`

§3 adds `scene_id: SceneId` as a kwarg on `JsonElementFactory.decode`
(only Dialog uses it in PR 4; signature is uniform so future composites
inherit it). The alternative is a per-kind decoder accepting `scene_id`
only where needed, but that splits the dispatch signature across kinds —
the uniform-keyword approach keeps one `decode(raw, *, scene_id)`
signature for every kind. **Question:** uniform kwarg (recommended),
per-kind specialization, or thread `scene_id` via a `DecodeContext`
value class composed into the factory?

### 6. ButtonClickEmitted naming

The io-model Event needs a name distinct from
`domain.interaction.ButtonClicked` (existing). §1 proposes
`ButtonClickEmitted`. Alternatives: `ButtonClickEvent`,
`ButtonClickedIO`. **Question:** confirm `ButtonClickEmitted`, or pick
another? The name is load-bearing for PRs 5–11 (every new Event class
in the io-model will follow the same naming convention).
