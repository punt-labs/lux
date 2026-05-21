# Design: Lux Domain Model — North Star

**Author:** Claude Agento (claude)
**Date:** 2026-05-21
**Status:** NORTH STAR (target state; not yet implemented)
**Companion:** `docs/architecture/x11-model.md` (process tiers)
**Audience:** anyone modifying `protocol/`, `display/`, `hub/`, or planning OO work

## Why this document exists

`x11-model.md` answers "where does the code run?" (client → hub → display, three
processes). This document answers "what does the code *hold*?" Together they
define the system: x11-model is the topology; this is the algebra.

We have been organising files, splitting modules, and adding type safety to
isolated corners. That is necessary but not sufficient. Without a domain model,
the code remains a collection of typed dictionaries that happen to deserialise
into dataclasses — never a model of what Lux *is*.

This document names what Lux is, in code-shaped terms, with invariants that
can be enforced and tested.

## The domain in one paragraph

**Lux is a multi-client shared display.** The display holds a composite tree
of typed visual elements. Each element belongs to one client. Clients submit
semantic updates against elements they own; the domain validates ownership,
applies the update, and emits an event. Renderers and serialisers subscribe
to events. The same domain model lives in the hub and the display server; the
two communicate by exchanging serialised updates and events. The domain is
independent of ImGui, JSON, and sockets — those are adapters at the boundary.

## Vocabulary

The nouns of the domain. These are the names code should use; deviating breaks
the model.

### Element

The base abstraction. Every visual thing on screen is an `Element`.

- **identity**: a string `id` unique within its enclosing `Scene`.
- **owner**: a `ClientId` — the client that created the element.
- **parent**: another `Element` (a container) or `None` if it's a direct
  child of the `Scene`.
- **lifecycle**: created, mutated, removed. Identity is stable across
  mutations.

Elements partition into two kinds:

- **Leaf** — holds renderable state, no children. `Text`, `Button`,
  `Slider`, `Image`, `Draw`. Each has its own typed state.
- **Container** — holds an ordered list of child Elements. `Group`,
  `Window`, `TabBar`, `CollapsingHeader`. Containers contribute layout
  metadata (orientation, tab names) but defer per-child rendering to
  the children themselves.

The Composite pattern (GoF) applies uniformly: every Element exposes the
same minimal interface to its parent — identity, owner, render contract —
regardless of whether it is leaf or container.

### Scene

The root of one composite tree. Has identity (`scene_id`), is owned by the
**Display**, and contains zero or more `Element` children. A Display holds
many Scenes; one is *active* at any moment.

A Scene is not an Element. Elements can be re-parented within a Scene;
they cannot move between Scenes. (Moving an Element across Scenes is
modelled as remove-then-add with a new id.)

### Client

The identity of one connected agent. Each `Client` has a unique `ClientId`
assigned at connection time. The Client *owns* the elements it creates and
can mutate only those elements. Disconnection cascade-removes the client's
elements from every Scene.

A Client is not an Element. It is a participant.

### Update

A semantic mutation request. The domain accepts five base Update kinds; every
mutation is one of these:

- `AddElement(scene_id, parent_id, element)` — insert a new element under
  a parent (or at scene root if `parent_id` is `None`).
- `RemoveElement(scene_id, element_id)` — remove an element and its
  subtree.
- `SetProperty(scene_id, element_id, field, value)` — change one typed
  property of an element.
- `ReparentElement(scene_id, element_id, new_parent_id, position)` —
  move an element within a Scene.
- `ReplaceElement(scene_id, element_id, new_element)` — replace an
  element with a new one of the same kind (preserves id and ownership).

Every Update carries the originating `ClientId`. The domain validates that
the client owns the target before applying. Unauthorised Updates do not
apply the requested mutation; instead the domain emits a single
`OwnershipError` event (see the Event vocabulary below) so subscribers
that need to react to refused mutations — error UIs, audit logs — see
them. No `ElementAdded` / `ElementUpdated` / `ElementRemoved` event
fires for a refused Update.

Full-scene replacement (today's mode of operation) is a degenerate case:
`RemoveElement(scene root) + AddElement(scene root, new tree)`. The wire
protocol may continue to carry it for bulk-load efficiency, but it is one
update sequence in the model, not a primitive.

### Event

What the domain emits in response to an Update — whether the Update
succeeded or was refused. Subscribers (Ports) listen to events to drive
renders, serialise to wire format, mirror to a peer, etc. Events
partition into two kinds:

**Success events** (the Update was applied):

- `ElementAdded(scene_id, element_id, parent_id, owner_id, snapshot)`
- `ElementRemoved(scene_id, element_id, owner_id)`
- `ElementUpdated(scene_id, element_id, field, old_value, new_value, owner_id)`
- `ElementReparented(scene_id, element_id, old_parent_id, new_parent_id, position, owner_id)`
- `ClientConnected(client_id)`
- `ClientDisconnected(client_id)`

**Failure events** (the Update was refused; no state change occurred):

- `OwnershipError(scene_id, element_id, attempting_client_id, owning_client_id, attempted_update)`
- `DuplicateIdError(scene_id, element_id, attempted_update)`
- `CycleError(scene_id, element_id, proposed_parent_id, attempted_update)`
- `PropertyTypeError(scene_id, element_id, field, expected_type, got_value, attempted_update)`

Events are immutable, ordered, and replayable. A new subscriber can
reconstruct a Scene by replaying the success-event log from the
beginning; failure events are advisory, not part of state recovery.

### Interaction

Input from a human at the display, routed through the domain to the
client that owns the affected element. Concrete kinds:
`ButtonClicked(element_id)`, `SliderMoved(element_id, value)`,
`TextInputChanged(element_id, text)`, `ItemSelected(element_id, index)`,
`TabSwitched(element_id, tab_index)`, `WindowClosed(element_id)`.

An Interaction is **not** an Update and **not** an Event. It is a third
shape: a signal originated by the renderer (the synthetic "input client")
that the Display routes to the element's owning Client as a message. The
Client's app code decides whether to respond by submitting an Update
(e.g., a button click that toggles a flag). The renderer never mutates
the tree directly in response to input.

### Port

An adapter at the boundary between the domain and an external concern.
A Port is not part of the domain — it lives in `display/`, `hub/`,
`transport/`, `test/`, etc., and is the one place that knows about
ImGui, JSON, sockets, or any specific I/O. Ports come in two flavours:

**Consumers** (subscribe to events; one-directional from domain → world):

- `ImGuiRenderer` — translates success events into ImGui draw calls and
  widget invocations. Owns no domain state; reads the Scene snapshot
  at frame time and walks the dirty subtree. Also originates
  `Interaction` signals from ImGui input.
- `EventRecorder` — captures the event stream for replay / audit.
- `TestRecorder` — captures events into a list for unit-test assertions.

**Codecs** (bidirectional; translate between domain types and external
formats):

- `JsonCodec` — `Update` ⇄ JSON, `Event` ⇄ JSON, used by the
  hub↔display socket transport.
- (future) `BinaryCodec`, `OtlpCodec` — any wire format is a new
  codec.

### Display

The shared substrate. Holds the set of Scenes and the live Client roster.
Routes Updates from Clients, applies them, emits Events. Holds the active
Scene pointer. Cascades client disconnections.

A Display is a singleton per seat. In tests, you instantiate one and exercise
the model end-to-end without launching a window or opening a socket.

## Structural invariants

The domain enforces these at construction and on every Update:

1. **Identity is unique within a Scene.** Adding an Element with an
   existing id in the same Scene raises `DuplicateIdError`.
2. **Ownership is immutable for an Element's lifetime.** A Client cannot
   transfer ownership to another Client.
3. **A Client mutates only its own Elements.** Cross-ownership
   `SetProperty`, `RemoveElement`, `ReparentElement`, `ReplaceElement`
   raise `OwnershipError`.
4. **Containers hold same-Scene children only.** A child Element's
   `scene_id` matches its parent's `scene_id`.
5. **The tree is acyclic.** A container cannot be made a descendant of
   itself. Reparent checks the proposed cycle and raises `CycleError`.
6. **Property updates are typed.** `SetProperty(element, "color", value)`
   requires `value` to match the declared type of `color` on that Element
   kind. Type-mismatch raises `PropertyTypeError` and emits no Event.
7. **Disconnection is transactional.** When a Client disconnects, every
   Element it owns is removed as a single sequence; partial cleanup is
   not observable.

These are the load-bearing rules. They live in the domain layer and are
enforced before any adapter sees the result.

## The rendering boundary — updates vs refresh

A frequent confusion this model eliminates:

- **Rendering updates** are domain-level. "This subtree changed" means
  the `ImGuiRenderer` (or any other consumer Port) should redraw it on
  the next frame. The domain marks subtrees dirty in response to
  Updates; it does not know about frames, 60fps, or pixels.
- **Refresh** is the renderer's loop. ImGui runs at 60fps; on every
  frame it walks the dirty subtree (or the whole tree, if performance
  permits) and issues draw calls. The domain has no opinion about
  refresh rate.

The same applies to input. ImGui detects a click; the renderer maps
the click coordinates to an Element identity and emits an `Interaction`
signal (see the Vocabulary). The Display routes the Interaction to the
Client that owns the Element. The Client's app code decides what to do
— typically it submits an `Update` (`SetProperty`, `RemoveElement`,
etc.) which then goes through the normal validation-and-emit cycle.

Interactions are not Updates and not Events. They sit between the
renderer and the domain: input on the way in, normal Updates and Events
on the way back out. ImGui keyboard repeat rates and event coalescing
live entirely on the renderer side.

## Ports — the adapter boundary

Concretely, every external concern is a port. Ports consume domain Events
and/or produce domain Updates. Ports live in `display/`, `hub/`,
`transport/`, etc. The domain in `protocol/` (or wherever we move it)
never imports a port.

```text
+------------------- Domain (protocol/) -------------------+
|                                                          |
|   Scene -> Element[Leaf|Container] -> properties         |
|   Update, Event, OwnershipError, DuplicateIdError, ...   |
|                                                          |
|   Display (one)                                          |
|     .apply(client_id, update) -> Event | Error          |
|     .subscribe(callback) -> Subscription                 |
|     .snapshot(scene_id) -> SceneSnapshot                 |
|                                                          |
+----------------------------------------------------------+
        ^                       |                       ^
        |                       v                       |
   +---------+         +-----------------+        +--------+
   | JsonCodec |       | ImGuiRenderer  |        | Tests  |
   | (wire IO) |       | (frame loop)   |        |        |
   +---------+         +-----------------+        +--------+
```

`JsonCodec` is bidirectional: it takes wire JSON, parses to typed Updates,
calls `Display.apply`. It also subscribes to Events and serialises them
back to wire JSON for the peer process.

`ImGuiRenderer` is one-directional from the domain's perspective: it
subscribes to Events and translates them. It also originates Interaction
events from ImGui input; those go *back* through the domain as input.

**The domain layer must not import** `imgui_bundle`, `json`, `socket`,
`asyncio`, or any I/O library. If `from imgui_bundle import X` appears in a
module under the domain layer, the model is broken.

## Runtime boundaries — hub and display

The hub (`luxd`) and the display server (`lux-display`) are different
processes (`x11-model.md`). They both hold the same domain model.
Concretely:

- The hub holds a `Display` (let's call it `hub_display`) that maintains
  the authoritative Scene state. Clients connect to the hub; their
  Updates flow into `hub_display`.
- The display server holds its own `Display` (let's call it
  `wire_display`) that mirrors `hub_display`. The hub forwards Events
  over the Unix socket; the display server applies them locally as
  Updates from a synthetic "hub client" to keep `wire_display` in sync.
- ImGuiRenderer is attached to `wire_display` and renders from there.
- Interactions (clicks, slider drags) originate on `wire_display`, are
  serialised by `JsonCodec` over the socket, applied to `hub_display`,
  and routed to the owning Client.

The two `Display` instances hold identical state by construction. The
serialisation layer is the only difference. In tests, both Display
instances run in one Python process and the "transport" is a direct
function call — no socket, no JSON encode.

## Testability — the single-runtime requirement

The domain must be testable without any GUI, socket, or process boundary.
Concretely, this test should be writable:

```python
def test_client_cannot_mutate_other_clients_elements() -> None:
    display = Display()
    alice_id = display.connect_client(name="alice")
    bob_id = display.connect_client(name="bob")

    display.add_scene("s1")
    result = display.apply(
        alice_id,
        AddElement("s1", parent_id=None, element=Button(id="b1", label="hi")),
    )
    assert isinstance(result, ElementAdded)

    refused = display.apply(
        bob_id, SetProperty("s1", "b1", "label", "evil")
    )
    assert isinstance(refused, OwnershipError)

    assert display.snapshot("s1").element("b1").label == "hi"
```

No ImGui. No socket. No `dict[str, Any]` shuffling. A real test of a real
invariant against real domain objects. If we cannot write tests like this,
we do not have a domain model.

## Where today's code falls relative to this

The frank assessment:

| Concept | Today | North star |
|---------|-------|------------|
| Element | `frozen=True` dataclass with public fields, no behavior | Stateful object with identity, owner, and validated mutators |
| Container children | `list[Any]` or `tuple[Element, ...]` | Same, but managed via `add_child`/`remove_child` that enforce invariants |
| Owner | Tracked in hub session table, not on the Element | First-class field on every Element |
| Update | Whole-scene replacement via `SceneMessage` | Five typed semantic primitives plus replay-compatible compositions |
| Event | Only `InteractionMessage` (input callbacks) | Full event vocabulary; every domain change emits one |
| Display | Implicit — the renderer reads the latest scene | Explicit `Display` class that holds Scenes, applies Updates, emits Events |
| Render boundary | Renderer pulls scene state directly | Renderer subscribes to Events; pulls snapshots at frame time |
| Ownership enforcement | Implicit (clients can only send Updates to scenes they're attached to, but cross-scene cross-client mutations are not forbidden) | Enforced at the domain layer; every Update is validated before apply |
| Tests | JSON roundtrip + visual smoke test | Domain-level: tree shape, ownership, event ordering, invariant violations |
| Code coupling | Some `protocol/` modules indirectly assume JSON via `_to_dict`/`_from_dict` shape; `element_renderer.py` knows every element kind | Domain has zero imports of `imgui_bundle`, `json`, or I/O libraries |

The draw-command surface (PR #176, #177) is the first piece that points
toward this north star: typed value classes, decoder at the wire boundary,
records that own their `to_dict` / `from_dict`. It is a single corner.
Most of the codebase is still in the left column.

## Migration path

A staged path that does not break the existing wire protocol:

### Stage 1 — name the domain

This document. Establishes vocabulary. No code change yet.

### Stage 2 — extract `Display`, `Client`, `Update`, `Event`

Introduce these classes in a new module (`src/punt_lux/domain/`).
`Display.apply(client_id, update) -> Event | Error`. `Display.subscribe(callback)`.
At first, the existing scene-message flow continues to work; the new
`Display` is parallel infrastructure.

### Stage 3 — make Elements live

Replace `frozen=True` dataclasses with mutable element classes that emit
events on mutation. Old frozen types become DTOs (`*Snapshot`) used only
at the wire boundary. The hub and display each hold a `Display` instance;
JSON wire input is parsed to a sequence of Updates and applied through it.

### Stage 4 — semantic updates on the wire

Add semantic Update kinds to the wire protocol. The agent can ship a
`SetProperty` directly instead of a whole `SceneMessage`. Backwards
compatibility: `SceneMessage` continues to work and is internally
translated to a `RemoveAll + AddElement` sequence.

### Stage 5 — decompose the renderer

`element_renderer.py` (today: one file, ~1,100 lines, dispatches every
element kind through a single `_RENDERERS` table) splits into per-kind
renderers that each subscribe to Events for their kind. The renderer
becomes a Visitor over the live tree rather than an imperative switch
over a snapshot dict.

### Stage 6 — split process boundary

Hub and display run as separate processes (the x11-model end state).
`JsonCodec` is the port between them. Both sides hold their own `Display`;
events flow from hub to wire-display over the socket. This is mechanical
once stages 2-5 are done.

Stages 2-3 are the hard part. They define the model. Stages 4-6 follow.

## What this means for the next PR

Anyone proposing a change to `protocol/elements/`, `hub/`, or `display/`
should be able to point at the cell in the "Today / North star" table
their change moves and say which direction. Moves left → right are
progress. Moves that stay in the left column without an explicit reason
are not. The OO ratchet enforces a weak version of this at the file level;
this document is the strong version for the system as a whole.
