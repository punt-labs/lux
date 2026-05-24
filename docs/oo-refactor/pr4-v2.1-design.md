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

Hard constraints (mission contract): (1) the 29 invariant MCP tools in
`src/punt_lux/tools/tools.py` keep their signatures; (2) no `PublishMessage`
external wire kind (ARCHITECTURE_NOTES A3); (3) interaction-layer collapse
(`Display.interact`, `DomainPump.route_interaction`, `ButtonClicked`,
`ButtonPressed`) is OUT OF SCOPE — PR 7 owns deletion; PR 4 lands parity
gate; (4) PY-OO-2 holds (≤ 300 lines, ≤ 3 classes per module).

---

## Section 1 — Module layout map

Every spike module touched by PR 4 maps to a production destination. Per-kind
split rule follows PY-OO-2 + PR 3's `protocol/elements/<kind>.py` convention.

| # | Spike construct | Production destination | Adaptation |
|---|---|---|---|
| 1 | `elements.py` ButtonElement (28–58) | `protocol/elements/button.py` (REWRITTEN) | Replace PR-2 dataclass with ABC subclass mirroring TextElement (§2). Keep production fields (action, disabled, small, arrow, tooltip) for snapshot parity. Sentinel defaults on renderer\_factory / emit per D1. |
| 2 | `elements.py` DialogElement (139–185) | `protocol/elements/dialog.py` (NEW) | Grep verified zero existing DialogElement in production. New file, no PR-2 carcass. Mirrors §3. |
| 3 | `codec.py` JsonButtonDecoder/Encoder (44–60, 188–190) | `protocol/elements/button_codec.py` (NEW) | Per-kind codec mirroring `text_codec.py`. Field set extended to match production Button. |
| 4 | `codec.py` JsonDialogDecoder/Encoder (93–145, 209–222) | `protocol/elements/dialog_codec.py` (NEW) | Per-kind module. Bound-callback dance lifted verbatim. |
| 5 | `codec.py` encode\_interaction / decode\_interaction (304–309) | NOT MIGRATED in PR 4 | Production `protocol/messages/interaction.py` `InteractionMessage` (load-bearing for legacy 8 inputs) already routes through MessageRegistry. |
| 6 | `codec.py` encode\_button\_clicked (312–313) | `protocol/elements/button_codec.py` (added as `JsonButtonClickedEncoder` class) | Spike free function becomes a small class (PY-OO-1) co-located with the Button codec. Used by hub emit dispatcher (§5). |
| 7 | `updates.py` RemoveElement (35–42) | `protocol/updates.py` — ADD RemoveElement (module exists from PR 3 carrying AddElement only) | Add the dataclass; extend Update sum to AddElement plus RemoveElement (no SetProperty — PR 5). |
| 8 | `updates.py` ButtonClicked (49–54) | `domain/events.py` (NEW) | Domain Event, separate from Updates. Existing `domain/interaction_event.py` `InteractionApplied` is the legacy event; both coexist until PR 7. |
| 9 | `hub.py` SubscriptionRegistry (132–166) | `domain/observer.py` (NEW) | Lift verbatim, adapted to asyncio per §4 (spike uses threading.Lock on blocking line-socket sends; production luxd is asyncio). |
| 10 | `hub.py` hub\_emit (197–215) + handle\_display\_message (235–255) | `hub/emit_dispatch.py` (NEW) — HubEmitDispatcher class | Lives alongside `tools/server.py` MCP session, NOT inside `src/punt_lux/hub.py` (WebSocket gateway — different responsibility). |
| 11 | `hub.py` handle\_agent\_message subscribe branch (259–262) | `tools/observer_tools.py` (NEW) + extension to `tools/server.py` registration | Subscribe/unsubscribe/publish exposed as MCP tools, additive to the 29 invariant. |

**Module-size check (post-PR 4):** every new file is < 130 LoC and ≤ 3
classes (PY-OO-2 OK). `button_codec.py` (3 classes) shares Button
vocabulary so PL-CO-3 holds. `dialog_codec.py` (2 classes), `observer.py`
(1), `emit_dispatch.py` (1), `observer_tools.py` (1).
`protocol/updates.py` grows from 1 dataclass to 2.

**One-file package.** `src/punt_lux/hub/` is new; the existing
`src/punt_lux/hub.py` (luxd WebSocket gateway) stays at the package root.
Resolves PR 3's §9 Q2: a one-file package is fine; PR 5+ populates it with
`hub_display.py`.

---

## Section 2 — ButtonElement on ABC

### Pattern source

Spike `elements.py` ButtonElement (60–106) is the template. Production
ButtonElement mirrors its `__new__`-keyword-only-injected pattern with the
fields the PR-2 dataclass already carried.

### Pre-design grep evidence

`grep -rn "ButtonElement(" src/ tests/` returns 66 lines (45 in tests, 21 in
src — mostly imports and one constructor per render test). Sentinel defaults
on renderer\_factory and emit (D1) are required: without them, the 45 test
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
    _action: str | None        # PY-TS-14 OK: action defaults to element id
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
        self._emit(ButtonClicked(element_id=self._id))
        if self._on_click_callback is not None:
            self._on_click_callback()

    # @property accessors for id, kind, label, action, disabled, small,
    # arrow, tooltip.  No @property for _on_click_callback — internal
    # wiring bound at decode time (per spike R4).
    # _set_<field> setters for the patch path (D6).
    # to_dict / from_dict thin delegators to button_codec (D5).
```

### ButtonClicked Event (where it lives)

Spike's ButtonClicked is `updates.py:49-54` and carries `elem_id: str`
only — its wire payload (`codec.py:312-313`) is `{"elem_id": eid}`.
Production puts it in `domain/events.py` (NEW), but extends the shape so
the parity gate (§8) compares a uniform `(element_id, action, value)`
triple against `InteractionMessage`:

```python
@dataclass(frozen=True, slots=True)
class ButtonClicked:
    element_id: str
    action: Literal["click"] = "click"        # constant for Button
    value: None = None                         # constant for Button
```

`action` and `value` are degenerate constants for the Button case — a
slider/input event class added later would carry a non-`None` `value`.
The triple shape stays uniform across event types; the parity gate
compares `(element_id, action, value)` from both paths without
case-by-case shape adapters. ButtonClicked is the io-model Event the ABC
Button raises through `self._emit`; legacy `InteractionMessage` (load-
bearing for the 8 unmigrated inputs) coexists until PR 7.

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
(93–145). Verbatim.

### Pre-design grep evidence

`grep -rn "DialogElement(" src/ tests/` returns 0 lines. No existing
DialogElement in production. New file, no PR-2 carcass, no sentinel-default
adaptation needed. ModalElement in `layout.py` is unrelated (it is the modal
popup container; PR 4 does not touch it).

### Production DialogElement (PR 4 — NEW)

`src/punt_lux/protocol/elements/dialog.py`.

```python
class DialogElement(Element):
    _id: str
    _children_tuple: tuple[Element, ...]
    _kind: Literal["dialog"]

    def __new__(cls, *,
                renderer_factory: RendererFactory = _NULL_FACTORY,
                emit: Emit = _no_emit,
                id: str,
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
        """Lifted from spike elements.py:181-185."""
        self._emit(RemoveElement(element_id=self._id))

    # @property accessors for id, kind.  to_dict / from_dict thin
    # delegators to dialog_codec (D5).
```

### Bound-callback decode (spike R4 pattern)

`src/punt_lux/protocol/elements/dialog_codec.py` — `JsonDialogDecoder.decode`
verbatim from spike `codec.py:117-145`:

```python
def decode(self, raw: Mapping[str, object]) -> DialogElement:
    dialog = DialogElement(
        renderer_factory=self._rf, emit=self._emit,
        id=str(raw["id"]), children=(),
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

`src/punt_lux/domain/observer.py` (NEW). Lifted from spike `hub.py:132-166`,
adapted to asyncio.

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
`observed` envelope back through the existing DisplayClient wire (D7
resolution: reuse the existing length-prefixed `InteractionMessage` channel
shape; a new `ObservedMessage` only if `MessageRegistry` proves inadequate
— see Open Question 2). The registry knows nothing about sockets, so it
tests with a `RecordingPush` fixture (PY-DP-9 Null Object).

### Hub-internal API

`hub.subscribe(cid, topic)`, `hub.unsubscribe(cid, topic)`,
`hub.publish(topic, payload)` are thin methods on whatever owns the Observer
instance per session. The current `tools/server.py` per-session state
already exists (each WebSocket session gets its own MCP server context); the
Observer joins that state. The session owner exposes
subscribe/unsubscribe/publish to internal callers (the emit dispatcher in
§5) AND wires the MCP tools below.

### MCP tool surface (additive)

`src/punt_lux/tools/observer_tools.py` (NEW). Three FastMCP tools, registered
in `tools/server.py` alongside the 29 invariant tools:

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

`connection_id` derives from the WebSocket session key (`hub.py:69` already
creates one per session). Subscribe/unsubscribe register/remove
`(topic, connection_id)`. Publish fans out via `Observer.publish`.

### Trust model

Per djb consultation: any agent can subscribe to any topic; any agent can
publish on any topic. No ACLs in PR 4. The model is trusted multi-tenant on
a single host — luxd binds to 127.0.0.1, CSWSH Origin allowlist already gates
browsers (`hub.py:74-78`). The implementation commit (ii) lands a small
"Trust model" subsection in `docs/architecture/io-model.md`. Later PR can add
per-topic ACLs if needed.

### Cascade on disconnect

When a WebSocket session closes (`hub.py:92-93` `_active_sessions.discard`
already fires), the session-owning code calls
`await observer.remove_connection(cid)`. The session-level lifecycle is the
right hook — Observer never owns the disconnect signal directly.

---

## Section 5 — Hub emit-handler dispatch

### Pattern source

Spike `hub.py:197-215` `hub_emit`. Per ARCHITECTURE\_NOTES A2: the emit
handler is the single fan-out point for everything an Element behavior raises
through `self._emit`. Two branches: Events → publish; Updates → accept +
ship.

### Production shape

`src/punt_lux/hub/emit_dispatch.py` — HubEmitDispatcher.

```python
class HubEmitDispatcher:
    """Satisfies the Emit Protocol.  JsonElementFactory passes
    `dispatcher.dispatch` as every ABC Element's `emit` channel."""

    _observer: Observer
    _send_update: SendUpdateFn
    _update_codec: UpdateCodec

    def __new__(cls, *, observer: Observer, send_update: SendUpdateFn,
                update_codec: UpdateCodec) -> Self: ...

    def dispatch(self, message: object) -> None:
        """Routes by type per A2."""
        match message:
            case ButtonClicked():
                topic = f"interaction.{message.element_id}"
                payload = JsonButtonClickedEncoder().encode(message)
                asyncio.create_task(self._observer.publish(topic, payload))
            case RemoveElement() | AddElement():
                # PR 4 ships the dispatch; full hub_display.accept lands
                # in PR 5.  See §11 Q3.
                wire = self._update_codec.encode(message)
                self._send_update(wire)
            case _:
                msg = f"Unknown message: {type(message).__name__}"
                raise ValueError(msg)
```

The `dispatch` method satisfies the Emit Protocol from
`protocol/renderer.py`: `Callable[[object], None]`. Synchronous wrapper
around async work — `asyncio.create_task` schedules publish on the event
loop the dispatcher was constructed inside. Behavior methods on Elements
stay synchronous (per spike: `def on_click(self) -> None`, not `async def`)
so the synchronous emit signature is the right contract.

### Where it plugs in

The session-owning code constructs:

1. The Observer (per-session push wraps the existing DisplayClient wire —
   §6, §11 Q2).
2. The HubEmitDispatcher (`observer`, `send_update`, `update_codec`).
3. The JsonElementFactory (`renderer_factory=NullRendererFactory()`,
   `emit=dispatcher.dispatch`) — so every ABC Element decoded from the
   wire gets the dispatcher as its emit channel.

`tools/tools.py:show()` calls `element_from_dict()`. PR 4 adds
`kind == "button"` and `kind == "dialog"` cases routing through the
per-session JsonElementFactory (D2 follow-up; Text already routes per
PR 3). The factory's emit is the dispatcher; behaviors `self._emit(...)`
funnel into `dispatcher.dispatch` per A2.

---

## Section 6 — First Observer consumer (`interaction.<id>` push — PY-RF-2)

### Pattern source

Spike `hub.py:235-255` `handle_display_message`: on inbound
InteractionMessage, decode → resolve on `hub_display` → if Button + click,
call `elem.on_click()` → emit ButtonClicked → publish `interaction.<id>` →
subscribers receive `observed(topic, payload)`.

### Production shape

The existing `tools/server.py` MCP session receives display-side
InteractionMessage via the existing DisplayClient listener path
(`display_client.py:309 _listener_loop`). PR 4 adds a parallel hub-side flow
for Button clicks. When the listener routes an
`InteractionMessage(element_id=X, action="click")`:

- Legacy path: the existing dispatch continues (load-bearing for the 8
  unmigrated inputs and for any agent that called `client.on_event()` per
  the current API). PR 4 does NOT remove this.
- New path: the per-session ABC ButtonElement registry (if X resolves to a
  Button on the hub-side `hub_display` mirror) ALSO invokes
  `elem.on_click()`, which raises ButtonClicked through `self._emit` →
  HubEmitDispatcher → `Observer.publish("interaction.X", {...})`.

For PR 4 the "hub-side `hub_display`" mirror lives inside the session-owning
code as a `dict[str, Element]` indexed when `show()` builds the Element tree
(per spike `hub.py:91-99` `HubDisplay._index`). PR 5 promotes this to a
proper HubDisplay class. PR 4 ships the minimal indexed dict; the structure
is the spike's `HubDisplay._by_id` minus the SetProperty branch (PR 5 owns).

### The load-bearing consumer

`interaction.<id>` IS the first real consumer of the Observer subsystem.
There is no manufactured `scene.accepted` or similar — `interaction.<id>` is
what agents need to react to clicks per spike R3/R4. This satisfies PY-RF-2:
the Observer is wired into a real call path the same commit it ships, not
"create now, wire later".

---

## Section 7 — `recv()` polling shim (deprecated for PR 12)

### Existing shape

`DisplayClient.recv()` (`display_client.py:565-583`) returns the next message
from a `_pending` queue, populated by the listener thread when it sees a
message with no registered callback. Tests and agents that pre-date the
Observer call `recv()` to block until the next InteractionMessage.

### PR 4 reimplementation

`recv()` is reimplemented as a polling adapter over the per-session
Observer using the wildcard subscription form specified in §4:

1. Subscribe a synthetic cid (`recv-shim-<session>`) to `WILDCARD_TOPIC`.
   The shim's push callback does not ship bytes — it appends the
   reconstructed InteractionMessage to an `asyncio.Queue` it owns.
2. Inbound InteractionMessage follows the §6 hub-side path (resolve →
   `on_click` → ButtonClicked → dispatcher → `Observer.publish`).
3. The wildcard branch fires the shim callback, which enqueues.
4. `DisplayClient.recv()` awaits the queue. Existing callers see the
   same InteractionMessage shape as before.

The queue lives in the shim, not in `Observer` — the registry only fans
out push calls (§4 invariant: it knows nothing about buffering). The
legacy `_pending` queue stays as the back-store for non-interaction
messages (AckMessage, PongMessage, etc.) that are never published.
Tests verify `recv()` returns the same shape it did pre-PR-4 (snapshot
fixture in commit (v)).

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
   → `ButtonPressed` → legacy InteractionMessage on the wire).
2. The new io-model path (display detects click → InteractionMessage on the
   wire → hub-side ABC ButtonElement → `on_click` → ButtonClicked Event →
   Observer publish).

Both paths produce the same triple shape because ButtonClicked carries
the same `(element_id, action, value)` fields as `InteractionMessage`
per §2 — for Button clicks the triple is always
`(<button_id>, "click", None)`. The parity gate is therefore field-level
equality on the same dataclass shape, not a cross-type adapter.

The test asserts the two paths produce equivalent traces for Button clicks.
This is the load-bearing proof that PR 4 has not broken the legacy path AND
that PR 7's deletion of the legacy path is safe.

### Implementation

`tests/regression/test_interaction_trace_parity.py` (NEW). The test:

1. Sets up a Display with a Button via `DisplayClient.show(...)`.
2. Records the legacy trace: triggers the click via the existing test
   harness (InteractionMessage synthesized into the display); captures what
   the listener dispatches.
3. Records the new trace: same click event, but observed via a subscribed
   `interaction.<id>` topic.
4. Asserts the recorded triples match by `(element_id, action, value)`.

Existing tests in `tests/test_inputs_migration.py` use the legacy path; the
parity test reuses those fixtures plus a new Observer fixture.

---

## Section 9 — Internal commit sequence

Seven commits per migration-plan.md PR 4 row 218. Each commit passes
`make check` + `make snapshot-parity` + local code-reviewer +
silent-failure-hunter + OO ratchet.

### (i) ButtonElement on ABC + JsonButtonDecoder/Encoder + headless behavior test

- **Create:** `protocol/elements/button_codec.py` (`JsonButtonDecoder`,
  `JsonButtonEncoder`, `JsonButtonClickedEncoder`).
- **Modify:** `protocol/elements/button.py` — REWRITE per §2 (delete
  dataclass; add ABC subclass with sentinel defaults D1; thin
  `to_dict`/`from_dict` delegators D5; `on_click` plus `_on_click_callback`;
  setters D6).
- **Modify:** `protocol/elements/__init__.py` — add `kind == "button"` route
  through JsonElementFactory; keep `_codec` fallback for the other 22
  unmigrated kinds.
- **Modify:** `protocol/elements/inputs.py:43` — `register("button",
  ButtonElement, ButtonElement.to_dict, ButtonElement.from_dict)` keeps
  working because the delegators are still on the class.
- **Tests:** `test_button_recording.py` (RecordingRenderer shape),
  `test_button_codec.py` (wire roundtrip, all field combinations),
  `test_button_on_click.py` (emits ButtonClicked; bound callback fires;
  uses `RecordingEmit` list-append per PR 3 pattern).
- **PY-RF-2 consumer:** `test_button_on_click.py`. Snapshot parity holds.

### (ii) RemoveElement + ButtonClicked + Observer + emit dispatcher + unit tests

- **Modify:** `protocol/updates.py` — add `RemoveElement` dataclass; extend
  `Update` type alias to `AddElement` plus `RemoveElement`.
- **Create:** `domain/events.py` — `ButtonClicked` frozen dataclass per
  §2 (triple shape `(element_id, action="click", value=None)`).
- **Create:** `domain/observer.py` — Observer class per §4.
- **Create:** `hub/emit_dispatch.py` — HubEmitDispatcher per §5.
- **Create:** `hub/__init__.py` with `__all__ = ["HubEmitDispatcher"]`.
- **Modify:** `protocol/update_codec.py` (PR 3 file) — add `RemoveElement`
  encode/decode case.
- **Tests:** `test_observer.py` (subscribe/unsubscribe/publish fan-out
  with `RecordingPush`; cascade-on-disconnect), `test_emit_dispatch.py`
  (ButtonClicked→publish, RemoveElement→encode+send, unknown→`ValueError`).
- **Doc patch:** "Trust model" subsection in
  `docs/architecture/io-model.md` per §4.
- **PY-RF-2 consumer:** dispatch test consumes Observer.

### (iii) MCP subscribe/unsubscribe/publish tools + server-push integration test

- **Create:** `tools/observer_tools.py` — `ObserverTools.register(mcp)` per
  §4.
- **Modify:** `tools/server.py` — instantiate per-session Observer (with
  per-session push callback that ships the `observed` envelope through the
  existing DisplayClient wire); register ObserverTools alongside the 29
  invariant tool registrations.
- **Tests:** `test_observer_mcp.py` — connect test MCP client; subscribe,
  publish; assert `observed(topic, payload)` push received (Starlette
  TestClient + WebSocket per existing harness pattern).
- **PY-RF-2 consumer:** the integration test.

### (iv) DialogElement + JsonDialogDecoder (bound-callback) + JsonDialogEncoder + headless dismiss test

- **Create:** `protocol/elements/dialog.py` per §3.
- **Create:** `protocol/elements/dialog_codec.py` per §3.
- **Modify:** `protocol/elements/__init__.py` — add `kind == "dialog"` route
  through JsonElementFactory; add DialogElement to the Element union;
  re-export.
- **Modify:** `display/element_renderer.py` — add `(DialogElement,
  "_dialog_renderer")` dispatch entry pointing to the new
  `display/renderers/imgui/dialog.py`.
- **Create:** `display/renderers/imgui/dialog.py` — minimal ImGui dialog
  renderer (per §3 last paragraph).
- **Tests:** `test_dialog_close.py` (emits RemoveElement(dialog.id)),
  `test_dialog_codec.py` (wire roundtrip; bound-callback: decode a wire
  dict with two child Buttons; assert each child's `_on_click_callback is
  dialog.close`), `test_dialog_recording.py` (composite walk).
- **PY-RF-2 consumer:** `test_dialog_codec.py` (bound-callback).

### (v) Hub publishes `interaction.<id>` on routed InteractionMessage + `recv()` polling shim + end-to-end test

- **Modify:** `tools/server.py` — when an InteractionMessage from the
  display arrives in the listener loop AND `element_id` resolves to a Button
  on the per-session hub state, invoke `elem.on_click()` (the dispatcher
  does the rest per §5 / §6).
- **Modify:** `display_client.py:309 _listener_loop` (or its server-side
  equivalent) — wire the polling-shim path per §7.
- **Tests:** `test_button_inbound_e2e.py` (display click →
  InteractionMessage → hub resolve → on\_click → publish → agent push),
  `test_recv_polling_shim.py` (pre-PR-4 `recv()` callers still receive the
  same InteractionMessage shape).
- **PY-RF-2 consumer:** the e2e test.

### (vi) End-to-end DialogElement test (R4 ported)

- **No source changes** — dispatch from (v) + Dialog from (iv) compose.
- **Tests:** `test_dialog_self_dismiss.py` — `Dialog{Label, Button(Yes),
  Button(No)}`; agent subscribes `interaction.btn_yes`/`btn_no`; click Yes;
  assert RemoveElement sent AND `interaction.btn_yes` push received.
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
| `recv()` polling shim works (existing agents unbroken) | `tests/integration/test_recv_polling_shim.py::test_recv_returns_interaction_message_via_observer`. |
| `make check` clean | OO ratchet, mypy/pyright, ruff format + lint, radon CC, pylint design. |
| Zero `to_dict`/`from_dict` on ButtonElement beyond delegators (D5) | `grep -A 4 "def to_dict\|def from_dict" src/punt_lux/protocol/elements/button.py` shows ≤ 3 lines per body delegating to JsonButtonEncoder/Decoder. |
| Zero `to_dict`/`from_dict` on DialogElement beyond delegators (D5) | Same grep on `dialog.py`. |
| All 29 invariant MCP tools continue to work | `grep -c "@mcp.tool\|@_query_tool" src/punt_lux/tools/tools.py` returns 29 (same as main). |
| 3 new Observer tools registered and additive | `grep -n "subscribe\|unsubscribe\|publish" src/punt_lux/tools/observer_tools.py` shows three tool definitions; integration test §9 (iii) verifies wire behavior. |
| JsonElementFactory routes Button + Dialog (D2 follow-up) | `grep -n 'kind == .button.\|kind == .dialog.' src/punt_lux/protocol/elements/__init__.py` returns exactly two lines. |
| Observer cascade-on-disconnect works | `tests/domain/test_observer.py::test_remove_connection_clears_all_topics`. |
| No PublishMessage wire kind | `grep -rn "PublishMessage" src/` returns zero. |
| No interaction-layer deletion | `grep -n "class ButtonPressed\|def route_interaction\|def interact" src/` returns the same lines as main (PR 7 owns deletion). |

13 new test files across `tests/render/`, `tests/protocol/`,
`tests/domain/`, `tests/hub/`, `tests/integration/`, `tests/regression/`
— each named in §9 commit (i)–(vii).  Create `tests/hub/` and
`tests/regression/` with empty `__init__.py` per existing pattern.

---

## Section 11 — Open questions for gvr / operator

Questions the spike and PR 3 pattern do not answer. Each needs an
explicit ruling before implementation.

### 1. SubscriptionRegistry concurrency primitive

Spike uses `threading.Lock` plus blocking send inside the lock
(`hub.py:154-166`). Production luxd is asyncio; §4 proposes `asyncio.Lock`
plus awaitable `PushFn`; alternative is snapshot-under-short-lock then
iterate outside. **Question:** `asyncio.Lock` (per §4) or
snapshot-then-iterate (per spike)? Matters when subscribe/unsubscribe
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
PR 4's resolve path works. The spike's full HubDisplay class
(`hub.py:49-123`) ships its `accept` branch in PR 5. **Question:**
minimal dict in PR 4 (recommended), or full HubDisplay class now (saves
PR 5 wiring; adds untested code)?

### 4. Trust model documentation patch

§4 lands a "Trust model" subsection in `docs/architecture/io-model.md`.
**Question:** OK to land in commit (ii) (recommended), or separate doc
PR?
