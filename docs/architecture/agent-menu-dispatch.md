# Agent Menu Dispatch — Why an Agent's `menu_set` Item Is Dead on Click, and the Full Fix

**Status:** design for bead `lux-m3xr` (P0). Aligns to
[target/target.md](target/target.md); on any conflict that document wins.
Read [target/ui-model.md](target/ui-model.md) and
[menu-capability-model.md](menu-capability-model.md) alongside this — the
model here is the callback model of DES-058/DES-061 generalized to reach a
plain MCP session, not a new one.

## Abstract

An agent registers a menu with the MCP `menu_set` tool. The item appears on
the bar. The user clicks it and nothing happens, while an applet's item
(`lux-beads`' *Beads*) works. Two independent defects sit behind the one
symptom, and the operator has ruled that both close — no frame-only shortcut.
This document specifies the full fix: gap (a), an agent item cannot carry a
`frame_id` through the decode; and gap (b), a frameless agent click reaches
the Hub and is *dropped* because the dispatch demands a callback leaf id an
agent item never has. The real design work is gap (b) — how a menu click
reaches the *owning MCP session* so a listening agent can act on it — and the
answer unifies agent-menu and applet-callback dispatch onto one Hub-side path
that forks only at delivery, exactly as the settled menu model already
prescribes.

## 1. Problem

There are two menu families in the code today, and they do not travel the same
path when clicked. One works; one is dead. The split is the defect.

### 1.1 Gap (a) — an agent item cannot carry a `frame_id`

`MenuAction` already has the field, `to_wire` already serializes it, and the
display already honors it:

- `MenuAction.frame_id` exists —
  `src/punt_lux/domain/hub/menu_models.py:39`.
- `MenuAction.to_wire` emits it when present —
  `src/punt_lux/domain/hub/menu_models.py:47`.
- The display's `WireAction.of_payload` reads it back —
  `src/punt_lux/display/menus/wire.py:113`.
- The display raises the frame when it is present —
  `src/punt_lux/display/menus/wire_decode.py:86-87`.

But the decode of an agent-supplied item never reads it.
`Menu._entry_from_wire` builds a `MenuAction` from only
`{id, label, shortcut, icon}` —
`src/punt_lux/domain/hub/menu_models.py:111-139`. So every agent item is
`frame_id=None` end to end, and the frame-raise branch never fires for it.

### 1.2 Gap (b) — a frameless agent click is dropped

The display always emits the same interaction for a menu click —
`RemoteEventHandlerInvocation(action="menu", element_id=<item id>)` —
`src/punt_lux/display/menus/wire_decode.py:85-96`. On the Hub the message
lands in the DisplayLink listener and routes to `HubInteractionDispatch`:

- `src/punt_lux/domain/hub/display_link.py:288-315` → `HubInteractionDispatch.dispatch`
- `src/punt_lux/domain/hub/hub_interaction_dispatch.py:40-49` → `_dispatch_menu_callback`
- `src/punt_lux/domain/hub/hub_interaction_dispatch.py:91-119`

`_dispatch_menu_callback` requires the leaf id to parse as a callback leaf —
`CallbackInvocation.from_menu_id`, which demands the composite
`connection_id<US>callback_id` shape
(`src/punt_lux/domain/hub/session_callback.py:89-100`). An agent item's id is a
bare string (`run_btn`, `agent_smoke`); it has no unit separator; the parse
raises `ValueError`; the code logs *"menu click for a non-callback leaf
id; ignoring"* and returns. The click is dropped.

### 1.3 Why the applet path works, and the two latent bugs beside gap (b)

An applet (`src/punt_lux/applets/leg.py:135-139`) registers a *callback*, not an
agent menu item. Its leaf id is the composite `connection_id<US>callback_id`
that `CallbackInvocation.menu_id` renders, and it carries a `frame_id`. So an
applet leaf both parses (routes to the owning session's held listener via
`CallbackRouter`) and raises its frame. It sidesteps *both* gaps by being on
the other family entirely.

Reading the agent-menu registry to design gap (b) surfaced two more defects on
the same code, which the fix must not leave behind (there is no "pre-existing"
excuse):

- **The agent bar is global, last-writer-wins.** `HubMenuRegistry` holds a
  flat `list[Menu]` and `set_menus` replaces it wholesale, with no record of
  which session registered it —
  `src/punt_lux/domain/hub/menu_registry.py:45-48`. Two Claude sessions calling
  `menu_set` clobber each other. Routing a click to "the owning session" is
  impossible while the registry does not record an owner.
- **A departed session's agent menus never leave.** The registry has no
  `drop_session`, so a `menu_set` from a session that has since disconnected
  persists on the bar forever. The callback family already withdraws on
  departure (`CallbackOperations.drop_session`); the agent family does not.

Both are prerequisites for gap (b): to deliver a click to the owning session,
the Hub must record the owner and release it on departure.

## 2. The settled model this fixes toward

[menu-capability-model.md](menu-capability-model.md) (DES-058) already ruled
what a menu item *is* — a session's callback, delivered to the session that
registered it — and named the exact failure this bead reproduces: *"a
durable-looking item whose click is dropped in the fallback handler."* It also
enumerated *"Pickup is routed by how the session connects"*: a persistent
socket is pushed to; an MCP streamable-HTTP session is served *"server stream
or session inbox"*; a periodic client's click is held and delivered on its next
beat. It named one open question — *"the MCP-stream delivery spike"* — can a
click be pushed to a live Claude Code session without polling, and if not, is a
*session inbox drained on the next call* the right v1 fallback.

This design resolves that spike for the plain-MCP-no-listener case: **a
`menu_set` click is delivered to the owning session's inbox and drained by
`recv()`**, and the dispatch that decides between "push to a listener" and
"enqueue on an inbox" becomes one path, forking by the live session's
capability — which is precisely *"routed by how the session connects."*

DES-061 (the 100 ms menu contract) is not contradicted. It governs
*callbacks*, which must *launch* something in the time a user reads as instant
and therefore require a held listen leg. A `menu_set` event is a different
interaction: an *agent-in-the-loop* notification — "the user selected the item
you own; act on it on your next turn" — the same character as an Agent
Subscribe business event. The two keep their own registration preconditions
(§4.3) and their own delivery legs (§4.2); only the dispatch entry is shared.

## 3. Gap (a) design — frame binding, and the item value model

### 3.1 The decode moves onto the class (PY-OO-5, PY-OO-7)

The fix for gap (a) is not "add one field read" in isolation; it is to put the
wire round-trip where it belongs and read `frame_id` as a byproduct. Today
`Menu._entry_from_wire` is a procedural classmethod that hand-decodes each
field of a `MenuAction` inline, with `_require_str`/`_optional_str` static
helpers beside it — the class holds `to_wire` but not `from_wire`, so the
inbound half of its own serialization lives outside it. That is the exact
"data owns its behavior" violation PY-OO-5 and PY-OO-7 name.

Move the round-trip onto the value types. `MenuAction.from_wire` reads every
field it round-trips — including `frame_id`, which closes gap (a). `Menu`'s
`_entry_from_wire` shrinks to a discriminator that delegates.

**BEFORE** (`menu_models.py`, the inbound decode lives on `Menu`, not on the
item, and omits `frame_id`):

```python
class MenuAction(BaseModel):
    ...
    frame_id: str | None = None

    def to_wire(self) -> dict[str, object]:
        item: dict[str, object] = {"label": self.label, "id": self.id}
        optional = {
            "shortcut": self.shortcut,
            "icon": self.icon,
            "frame_id": self.frame_id,
        }
        item.update((k, v) for k, v in optional.items() if v is not None)
        return item


class Menu(BaseModel):
    @classmethod
    def _entry_from_wire(cls, item: object, *, loc: str) -> MenuEntry:
        ...
        if raw_id is not None:
            return MenuAction(  # frame_id never read
                id=cls._require_str(raw_id, loc=f"{loc}.id"),
                label=cls._require_str(entry.get("label"), loc=f"{loc}.label"),
                shortcut=cls._optional_str(
                    entry.get("shortcut"), loc=f"{loc}.shortcut"
                ),
                icon=cls._optional_str(entry.get("icon"), loc=f"{loc}.icon"),
            )
        ...
```

**AFTER** (the item owns both halves; the discriminator delegates):

```python
@runtime_checkable
class WireMenuEntry(Protocol):
    """A menu entry that round-trips itself. The family contract, structural."""

    TYPE: ClassVar[str]

    def to_wire(self) -> dict[str, object]: ...


class MenuAction(BaseModel):
    ...
    # absent = the action owns no frame to raise (like SessionCallback.frame_id
    # and tooltip: a genuine "no owned frame" state, not a deferred decision).
    frame_id: str | None = None

    @classmethod
    def from_wire(cls, entry: Mapping[str, object], *, loc: str) -> Self:
        return cls(
            id=_require_str(entry.get("id"), loc=f"{loc}.id"),
            label=_require_str(entry.get("label"), loc=f"{loc}.label"),
            shortcut=_optional_str(entry.get("shortcut"), loc=f"{loc}.shortcut"),
            icon=_optional_str(entry.get("icon"), loc=f"{loc}.icon"),
            frame_id=_optional_str(entry.get("frame_id"), loc=f"{loc}.frame_id"),
        )


class Menu(BaseModel):
    @classmethod
    def _entry_from_wire(cls, item: object, *, loc: str) -> MenuEntry:
        entry = _require_mapping(item, loc=loc)
        if entry.get("id") is not None:
            return MenuAction.from_wire(entry, loc=loc)
        if entry.get("label") == _SEPARATOR_SENTINEL:
            return MenuSeparator()
        raise ValueError(f"{loc}: an id-less entry must be the separator")
```

The `_require_str` / `_optional_str` / `_require_mapping` helpers stay
module-level utilities (they are the "primitives module" legitimate exception
to PY-OO-7 — stateless wire predicates shared by several entry classes, not
methods of any one of them). The family shares by the `runtime_checkable`
`WireMenuEntry` Protocol, not a base class (families-share-by-Protocol); the
existing pydantic discriminated union on `kind` stays as the runtime shape, and
tests assert `isinstance(action, WireMenuEntry)` for the contract.

### 3.2 Why `frame_id` stays an optional field, not a discriminated state

PY rule 5 (reduce `| None`) asks, per field, whether the `None` is a
discriminated state that reads better split. Here it is *not*, and the split
would be wrong. An action with a `frame_id` **both** raises that frame
(Display-local, DES-088) **and** emits its click; the two behaviors *compose*,
they are not exclusive. A discriminated `RaisesFrameAction | DeliversClickAction`
would falsely claim a frame-bound item does not deliver a click. `frame_id` is
therefore a genuine optional attribute — absence is the real, documented state
*"this item owns no frame to raise"*, the same shape `SessionCallback.frame_id`
already carries (`session_callback.py:43`). Keeping them the same shape is the
one-frame-binding-model consistency the callback path and the agent path should
share; the Optional is justified in place, per PY-TS-14, and the discriminated
alternative is rejected on the merits.

### 3.3 Frame-raise and click delivery compose

Gap (a) and gap (b) are orthogonal and both fire for one item. An agent item
naming a `frame_id` it owns (a frame it created with `show(..., frame_id=...)`)
raises that frame *Display-locally and immediately* on click — no Hub round
trip, per DES-088 "only the Display moves a frame" — **and** the same click
flows to the owning session's inbox (§4) so the agent is told the user acted.
"Open my dashboard and let me react" is one item, two effects.

## 4. Gap (b) design — the click reaches the owning MCP session

### 4.1 Decision: deliver to the owning session's inbox, drained by `recv()`

A `menu_set` click is delivered to the registering session's existing inbox as
a reserved-topic UI event, and the agent drains it with the `recv()` tool it
already has. No new standing MCP tool. This makes the current `menu_set`
docstring's promise — *"clicks arrive via recv()"* — true, and it spends
machinery that already exists and is departure-correct: the per-connection
`ObserverMessage` inbox (`domain/hub/inbox.py`) and the `topic_recv` drain
(`tools/subscribe_tools.py:86-96`).

The event is an `ObserverMessage` on a **reserved `lux.menu` topic** the Hub
owns, distinct from agent-defined topics, so it is self-identifying and cannot
collide with a topic the agent declared:

```text
recv() -> "event:lux.menu:{\"menu\":\"Tools\",\"item\":\"run_btn\"}"
```

`recv()`'s contract is refined, narrowly: a **menu selection** is an
agent-level business event and *is* delivered here (ui-model.md itself lists
`item.selected` as a pub-sub business event, line 108); low-level **scene-element
wire frames** — a slider drag, an in-scene button click that fires a Hub-side
handler on the D21 path — are still *not*. The boundary moves from "no UI
events at all" to "menu selections yes, scene-element frames no," which is the
honest line: a menu selection is what the *user asked the agent to do*, not a
render-loop input.

### 4.2 One dispatch path, forking by the leaf's kind (as shipped)

> **Shipped contract.** This section originally proposed forking by the live
> session's *capability* (infer callback-vs-menu from whether a callback with
> that id exists). Implementation review found that ambiguous: a session owning
> both a callback and a `menu_set` item with the same raw id would mis-route the
> menu click to the callback. The shipped design therefore makes the leaf id
> **kind-tagged** and forks by the leaf's own kind. The kind-tagged text below is
> authoritative.

`HubInteractionDispatch._dispatch_menu_click` is the single menu-click path.
Every menu leaf — applet callback and agent item alike — renders a routable,
**kind-tagged** leaf id `kind<US>owner_connection_id<US>item_id`, where `kind`
is `cb` (callback) or `mi` (agent menu item); the Hub stamps the owner (the
agent never sees or supplies a connection id). The dispatch parses *every* leaf
once with `MenuLeaf.parse` and forks on the leaf's **own kind** — not by
inferring capability from callback existence:

```text
_dispatch_menu_click(leaf_id):
    leaf = MenuLeaf.parse(leaf_id)          # one parse, every leaf; carries kind
    if leaf.is_details:        -> hub_client_details.run(conn)        # Hub answers
    if leaf.kind == "cb":      -> CallbackRouter.route(...)           # applet listener
    if leaf.kind == "mi":      -> resolve owning LIVE session:
                                    live inbox  -> enqueue lux.menu event  # agent
                                    gone/none   -> provider_gone: log + re-push
```

The bare-id `ValueError`-drop is deleted. There is one entry, one parse, and a
kind-based fork. The kind tag is load-bearing: it is what keeps a `menu_set`
item and a same-named callback in one session from being confused — an `mi`
item is delivered to the inbox even when its owner also holds a listener — so
the discriminator must not be removed. An agent item and an applet item travel
the same dispatch and differ only in the kind carried in their leaf id.

`Details` is already on this unified shape today: its leaf id is the composite
`conn<US><US>details` that parses, `is_details` is true, and the Hub answers it
itself. It does **not** share gap (b) — it is the model to generalize, and the
proof that a Hub-handled menu leaf already works when its id is routable.

### 4.3 Registration: two surfaces, two preconditions, one ownership model

The two registration surfaces keep distinct preconditions, because they promise
different things:

- `register_callback` (applet) requires a **held listen leg** — DES-061's 100 ms
  contract — so the click can *launch* work with no model turn. Unchanged.
- `menu_set` (agent) requires only an **identified session** — so the leaf id
  can be stamped with a durable owner and the item withdrawn on departure — and
  that session's **inbox writer + departure sink is armed** (reuse
  `inbox.ensure_writer`) so a click has somewhere to land and is released when
  the session leaves. Anonymous ownership is refused, mirroring the callback
  path's *"nothing anonymous owns a menu item."*

`HubMenuRegistry` becomes session-keyed: `set_menus(connection_id, menus)`,
`drop_session(connection_id)`, and `wire_snapshot()` composes every live
session's bar with each leaf id stamped `owner<US>item_id`. This closes the
global-clobber and never-withdrawn latent bugs from §1.3 in the same change,
and puts the agent family on the same session-ownership footing as the callback
family without collapsing the agent-defined top-level menu structure — an agent
keeps its custom `Tools` menu; it is simply owned by, and delivered to, the
session that registered it. `MenuAction.id` gains the same separator rejection
`SessionCallback` enforces, so a stamped leaf id never splits ambiguously.

## 5. Rejected alternatives for gap (b)

- **B1 — make `menu_set` items first-class callbacks (require a listen leg).**
  Rejected. It forces every agent that wants a menu affordance to run an applet
  or hold a `LuxClient.listener` leg, collapsing `menu_set` into
  `register_callback` and deleting the agent-in-the-loop affordance the
  operator's smoke test exercised. The contract's own words for gap (b) —
  reach the owning MCP session *"so a listening agent can act on it"* — describe
  a next-turn notification, not a sub-100 ms push. A plain MCP session has no
  listener by construction; B1 does not reach it, it excludes it.

- **B2b — a dedicated `menu_recv` MCP tool over a separate menu-event inbox.**
  Rejected in favor of reusing `recv`. It adds a standing tool to every agent's
  contract, which DES-040 ("small surface on purpose") and the bead's own
  guidance ("prefer extending an existing drain over adding a standing tool")
  argue against. A menu selection is a business event of the same character
  `recv` already carries; the reserved `lux.menu` topic keeps it
  self-identifying without a second drain. The chosen B2a reuses `recv`.

- **B3 — hybrid: enqueue on the inbox *and* push to a listener when both
  exist.** Rejected as redundant. The delivery leg is already chosen by the live
  session's capability at click time (listener → push; else inbox); a single
  item does not carry both semantics, so "both" would double-deliver with no
  second consumer. The capability-fork of §4.2 *is* the principled hybrid —
  one item, one leg, chosen by how its owner connects.

## 6. Z-spec determination

> **Shipped outcome.** The tripwire named below *fired*: implementation added a
> new lock discipline (D3's `StoreLock → HubMenuRegistry._lock`) and review
> surfaced departure/interleaving edges, so z-spec became **required**. The
> committed artifacts are `docs/menu_lifecycle.tex` + `docs/menu_lifecycle_delivery.tex`
> (and their `_buggy` fidelity controls + `menu_lifecycle_coverage.md`),
> `fuzz`-clean and ProB-checked at setsize 3, deadlock-free — proving M1
> (no orphan-put false delivery), M1b (no live-recipient loss under the
> offer-then-drop reorder), and MO (ownership integrity), each with a control
> that reproduces the defect when its guard is removed. The design-time reasoning
> below is retained as the record of why the tripwire was the right gate.

**Determination (design-time): z-spec is NOT newly required — the change reuses
proven mechanics — with one named tripwire that flips it to required.**

The delivery fork reuses two already-modeled disciplines and introduces no new
lock and no new acquisition order:

1. **The applet-callback leg is unchanged.** `CallbackRouter` routes under its
   one lock after a lock-free live read, sweeping departed sessions' holds on
   the way in (`callback_hold.py`). Its departure/reap discipline is the
   subject of `docs/connection_lease_reaping.tex` — the four-step departure
   cascade (registry, ownership, subs+writer/inbox sink, timed backstop) with
   invariants
   I1 (a transport-gone connection is unconditionally eventually reaped), I5
   (leaving the registry and releasing ownership are one event), I3 (a live
   reconnect is never shadowed by a departed predecessor).

2. **The new inbox leg reuses Agent Subscribe's inbox.** The enqueue is one more
   producer on the existing per-connection `SimpleQueue` (`inbox.py`), whose
   put/get are thread-safe and whose allocation and `drop_session` removal are
   guarded by `_inboxes_lock`. The departure sink that releases the inbox
   (`drop_session`, armed by `ensure_writer`) is the *same* subs+writer sink the
   cascade above already models.

The one genuinely new edge — a menu-event enqueue racing the owning session's
reap — is the **same class** as "a callback click races a reap," which the
cited model already proves. The implementation must gate the enqueue behind the
**same live-session read** `CallbackRouter.route` uses (check live under the
client-registry read, then enqueue-or-`provider_gone`), touching the same two
locks (client-registry read, then the queue's own lock) in the same order the
router already touches them. Under that gate, the three delivery invariants
reduce to results the model already holds:

- **M1 — a menu event is never delivered to a departed session.** Reduces to
  the router's proven *"a click for a lapsed session is `provider_gone`, its
  hold swept"* plus `drop_session` popping the inbox on departure (a straggler
  put after the pop lands in an orphaned queue that is GC'd — no delivery, no
  leak).
- **M2 — a menu event is delivered at most once.** `SimpleQueue.put` once,
  `recv` `get`/drain once; no re-enqueue path.
- **M3 — no menu event is lost while a reconnect races a reap.** The enqueue
  runs under the same store read that makes I3 hold for the callback leg; a live
  reconnect under the same identity is the live session the read returns.

**The tripwire (honest, and binding on the implementer).** IF, in
implementation, the enqueue cannot be ordered by reusing that existing store
read — for example if delivering a menu event needs a *new* lock held across the
inbox `drop_session`, or a new "menu-registry lock ↔ inbox lock ↔
client-registry lock" acquisition order appears — THEN the change enters the
concurrency class and z-spec becomes **required**: model M1/M2/M3 over a bounded
carrier with a fidelity control that reproduces the drop when the live-gate is
removed, per repo policy. rmh (implementer) must stop and model if that ordering
materializes rather than reason about it empirically.

The `HubMenuRegistry` session-keying stays within the class's existing "one
independent lock, never held across another lock or any I/O" discipline
(`menu_registry.py:11-16`); swapping its `list` for an owner-keyed `dict` under
that same single mutex adds no acquisition ordering. Its new `drop_session` is
one more sink on the departure cascade already modeled — structurally identical
to the inbox sink the model covers — and is covered by the same argument, with
the same tripwire.

## 7. Implementation write-set

The design's product. The implementer decides the final split; this is the
concrete surface each change lands on.

### 7.1 Gap (a) — frame binding

- `src/punt_lux/domain/hub/menu_models.py` — add `MenuAction.from_wire` (reads
  `frame_id`; the fix), `MenuSeparator.from_wire`; reduce `Menu._entry_from_wire`
  to a discriminator delegating to them; add the `runtime_checkable`
  `WireMenuEntry` Protocol; add `MenuAction` id-separator rejection (gap-b
  prerequisite). OO improvement carries the ratchet on this file.
- `src/punt_lux/tools/display_write_tools.py` — `menu_set` docstring/schema
  documents the optional per-item `frame_id` and that clicks arrive via `recv()`.
- `src/punt_lux/operations/models/menu_results.py` — verify `SetMenuRequest.parse`
  flows the new decode through `Menu.from_wire` unchanged (no shape change; the
  owner arrives from scope at the operation, §7.2).

### 7.2 Gap (b) — ownership, dispatch, delivery

- `src/punt_lux/domain/hub/menu_registry.py` — session-key the registry:
  `set_menus(connection_id, menus)`, `drop_session(connection_id)`, and
  `wire_snapshot()` stamping every leaf id `owner<US>item_id`. Closes the
  global-clobber and never-withdrawn bugs.
- `src/punt_lux/operations/menus.py` — `MenuOperations.set_menu(request, *, scope)`
  records the owner and arms the session's inbox writer + departure sink
  (`ensure_writer`); a `drop_session` re-push mirroring `CallbackOperations`.
- `src/punt_lux/domain/hub/hub_interaction_dispatch.py` — `_dispatch_menu_callback`
  becomes the one menu path (§4.2): parse every leaf, `is_details` unchanged,
  fork by live-session capability (listener → `CallbackRouter`; inbox → enqueue;
  gone → `provider_gone` + re-push). Delete the bare-id drop.
- `src/punt_lux/domain/hub/inbox.py` — the gated enqueue helper that puts a
  reserved-topic `lux.menu` `ObserverMessage` on the owner's inbox, behind the
  live-session read (or a sibling `menu_event.py` if that keeps `inbox.py` under
  the size cap).
- `src/punt_lux/operations/` — the delivery is invoked through the operations
  facade (a method on the menu/callback concern), so the dispatch stays a thin
  router and every surface shares the one code path.
- `src/punt_lux/tools/subscribe_tools.py` — refine `recv`'s docstring per §4.1
  (menu selections delivered; scene-element frames not).
- The disconnect cascade wiring (where `inbox.drop_session` and the callback
  drop are bound) — bind `HubMenuRegistry.drop_session` as one more departure
  sink.

### 7.3 Tests

- `tests/domain/hub/test_menu_models.py` — `MenuAction` round-trip with and
  without `frame_id` (build → `to_wire` → `from_wire` → compare); `isinstance`
  against `WireMenuEntry` for the family; id-separator rejection; malformed
  `frame_id` rejected by name.
- `tests/domain/hub/test_hub_interaction_dispatch.py` — **the gap-(b)
  regression:** a frameless agent menu click for a live inbox session is
  *delivered* (the `lux.menu` event lands on the inbox / `recv` returns it), not
  dropped; a click for an applet (listener) session routes to the callback hold;
  a click for a departed session → `provider_gone`, *not delivered*; `Details`
  still runs; boundary — a malformed leaf id is an `invalid_request`, no crash.
- `tests/domain/hub/test_menu_registry.py` — session-keyed set/drop/snapshot;
  two sessions do not clobber; a departed session's menus leave; leaf ids
  stamped with the owner.
- A surface/integration test — `menu_set` from one identified session then
  `recv` from that session returns the `lux.menu` click event: the full
  agent-visible loop, the demo-gate proof.

Happy / invalid / boundary / missing-dependency coverage: happy — item click →
`recv` event; invalid — malformed leaf id logged, no crash; boundary — click at
the instant the owner departs → `provider_gone`, plus the hold/inbox
over-capacity drop; missing-dependency — a session with neither listener nor
inbox (should not occur post-identify) → `provider_gone`, never a silent drop.

## 8. Proposed ADR

Append DES-098 (below) to [DESIGN.md](../../DESIGN.md); it is the settled record
of this decision.

## Related documents

- [target/target.md](target/target.md) — the Hub-authoritative model.
- [target/ui-model.md](target/ui-model.md) — handlers on Hub-side objects,
  application pub-sub vs UI events, `item.selected` as a business event.
- [menu-capability-model.md](menu-capability-model.md) — the callback model
  (DES-058), the pickup-by-connection-kind routing, and the delivery spike this
  resolves.
- `docs/connection_lease_reaping.tex` — the departure cascade the delivery
  invariants reduce to.
