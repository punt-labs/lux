# Dynamic Attribute Access: Design Debt and Path Forward

`hasattr`, `setattr`, and `getattr` are type system bypasses. Every
occurrence in the codebase is a symptom of a missing typed abstraction.
This document records what was found, what was fixed, and what remains.

---

## What Was Found (as of 2026-05-15)

Three call sites used dynamic attribute access on protocol element and
message instances:

### Site 1 — `protocol/elements.py`: tooltip stamping during deserialization

```python
# Before
if tooltip is not None and hasattr(elem, "tooltip"):
    elem.tooltip = tooltip
```

The deserializer received an `Element` (a union of 27 types) and probed
at runtime whether the concrete type supports a `tooltip` field. This
was necessary because the deserializer operated on the union type, not
on a per-type basis.

**Fix applied:** `dataclasses.replace(elem, tooltip=tooltip)`. This
still assumes the field exists but no longer mutates a (now-frozen)
instance.

**Remaining debt:** The deserializer should be per-type, not generic.
Each element type that supports `tooltip` should handle it in its own
`from_dict` classmethod. The `hasattr` check would then be unnecessary
because the type system would know statically which elements have it.

### Site 2 — `scene/manager.py`: field patching in `_apply_patch_set`

```python
# Before
for k, v in fields.items():
    if k in ("id", "kind"):
        continue
    if hasattr(elem, k):
        setattr(elem, k, v)
```

An agent sends `{"value": true, "label": "foo"}` over the wire. The
scene manager iterates over the dict and applies fields that exist on
the element. The `hasattr` check was the type-safety mechanism — if a
field name in the patch doesn't exist on the element, skip it silently.
This means invalid patches fail silently rather than raising an error.

**Fix applied:** `dataclasses.replace(elem, **valid)` where `valid`
filters out `"id"` and `"kind"`. The frozen constraint now ensures
the replace is the only mutation path.

**Remaining debt:** `dict[str, Any]` patches are the core problem. The
`setattr` pattern was an artifact of the patch being untyped. See
"Path Forward" below.

### Site 3 — `display/server.py`: scene_id stamping on events

```python
# Before
if event.scene_id is None:
    event.scene_id = self._current_scene_id
```

Direct attribute assignment on a `InteractionMessage` instance. The
intent was to stamp the current scene context onto events that don't
carry one. Straightforward mutation of a value object.

**Fix applied:** `dataclasses.replace(event, scene_id=self._current_scene_id)`.
Test updated from identity check (`is`) to field equality since a new
instance is now returned.

---

## Why `hasattr`/`setattr`/`getattr` Are Type Design Smells

These functions bypass the type system entirely. When you write
`hasattr(obj, "field")`, you are doing at runtime what the type checker
should do at compile time. The need to probe means either:

1. **The type is wrong** — you're holding a union or base type when you
   should be holding the concrete type that has the field.
2. **The operation is wrong** — the logic belongs as a method on the
   class, not as an external function probing the class.
3. **The data model is wrong** — a `dict[str, Any]` is standing in for
   a typed patch object.

In every case, the correct fix is to push the logic into the type
system, not to live with dynamic dispatch.

`getattr(obj, "id", None)` is the same smell: if `id` is a known field
on `Element`, it should be a property on the `Element` base class or
protocol, not a runtime probe. If it's not always present, that's a
type design issue — all elements should have an `id` or none of them
should.

---

## The Root Cause: Wire Types Used as Scene Graph Nodes

The three sites above are symptoms of one structural problem: the
protocol dataclasses serve two incompatible roles simultaneously.

**Role 1 — Wire protocol.** `ShowMessage`, `TextElement`, `SliderElement`
and the rest describe what an agent wants to render. They cross the
WebSocket from the agent to `luxd`, are deserialized, applied to hub
state, and discarded. Short-lived. Never stored. Immutable is correct
here: a wire message is a command, not a persistent object.

**Role 2 — Scene graph nodes.** The same objects are stored in
`SceneManager._scenes` and updated incrementally by `apply_update`. They
are retained for the lifetime of the scene. Mutable is correct here: the
hub receives patches from agents and must apply them to existing state.

These roles have opposite requirements. The `hasattr`/`setattr` patterns
existed precisely because the code needed to mutate objects that were
typed as if they were immutable value types. Adding `frozen=True` made
the conflict explicit: now `apply_update` calls `dataclasses.replace()`
to produce a new frozen instance from an old one and swaps it into the
scene's `elements` list — while the `elements` list itself is mutable
because it is stored in a frozen `SceneMessage`. The frozen/mutable
boundary is incoherent: the message is frozen, the list inside it is
mutable, the elements inside the list are frozen, lists inside those
elements are mutable.

`frozen=True` on the protocol types was the right move for the wire role
and the wrong model for the scene graph role. The fix is not to
un-freeze them. The fix is to separate the two roles into distinct types.

## The Three-Layer Type Model

Three distinct data roles require three distinct type layers.

### Layer 1 — Wire types (what they are now, frozen is correct)

Objects that cross the WebSocket boundary from agent to hub. Created by
the agent, deserialized by the hub, used to drive a scene graph update,
then discarded. These are commands, not state.

`frozen=True, slots=True` is correct here. They are value objects in
the strict sense: stateless, short-lived, compared by value, passed
around without ownership concerns.

```python
# protocol/wire.py — already approximately correct
@dataclass(frozen=True, slots=True)
class ShowMessage:
    scene_id: str
    elements: tuple[WireElement, ...]
    client_id: str
    ts: float
```

The wire types define the JSON API surface. Any agent in any language
that can serialize this JSON can drive the display. Their structure is
determined by the protocol, not by the needs of the scene graph.

### Layer 2 — Scene graph nodes (do not exist yet, mutable is correct)

The hub's authoritative retained state. Updated incrementally by
incoming wire commands. Owned exclusively by the hub. Never shared with
the renderer directly.

These should be mutable classes — one per element kind — with typed
update methods:

```python
# scene/nodes.py
class SliderNode:
    id: str
    value: float
    min: float
    max: float
    label: str

    def apply(self, patch: SliderPatch) -> None:
        if patch.value is not None:
            self.value = patch.value
        if patch.label is not None:
            self.label = patch.label
```

`frozen=True` is wrong here. These objects exist to be updated. Direct
mutation is correct because the hub owns them exclusively — no concurrency
concern exists within the hub's event loop. The typed `apply()` method
replaces `dataclasses.replace(**dict[str, Any])`: the type system
enforces which fields can be patched on which element kind at compile
time, not at runtime via field-name filtering.

### Layer 3 — Display snapshot (do not exist yet, frozen is correct again)

What crosses the Unix socket IPC boundary from `luxd` to `lux-display`
once per render frame. The hub builds a snapshot from the current scene
graph state and pushes it to the renderer. The renderer consumes it and
discards it.

`frozen=True` is correct here for a different reason than Layer 1: the
snapshot crosses a concurrency boundary. The renderer reads it during a
frame while the hub may be computing the next one. An immutable snapshot
eliminates the race without a lock.

```python
# scene/snapshot.py
@dataclass(frozen=True, slots=True)
class DisplaySnapshot:
    scenes: tuple[SceneSnapshot, ...]
    ts: float

@dataclass(frozen=True, slots=True)
class SceneSnapshot:
    scene_id: str
    elements: tuple[ElementSnapshot, ...]
```

The snapshot is derived from the scene graph, not stored in it. The hub
calls `snapshot()` on the scene manager when it needs to push to the
renderer — either on every patch or on a coalescing timer. The renderer
receives it, renders it, and drops it. The scene graph continues to
evolve independently.

### The full data flow

```
Agent (any language)
  │  wire types (frozen, short-lived)
  │  WebSocket / MCP JSON-RPC
  ▼
luxd session hub
  │  applies wire commands to scene graph
  ▼
Scene graph (mutable nodes, hub-owned)
  │  snapshot() — produces immutable snapshot
  ▼
DisplaySnapshot (frozen, point-in-time)
  │  Unix socket IPC
  ▼
lux-display ImGui renderer
  │  renders snapshot, discards it
  ▼
Framebuffer (60 fps)
```

The three layers have independent lifetimes. Wire objects live for one
request. Scene graph nodes live for the lifetime of a scene. Snapshots
live for one render frame. Conflating any two of these lifetimes into
one type produces the kind of contradiction visible in the current code.

---

## Path Forward

### Typed patches per element kind

The root cause of Site 2 is `UpdatePatch.set: dict[str, Any]`. The
patch is untyped because flexibility was prioritized over correctness:
agents can send any subset of fields for any element, and the runtime
figures it out.

The typed alternative:

```python
@dataclass(frozen=True, slots=True)
class SliderPatch:
    value: float | None = None
    min: float | None = None
    max: float | None = None

@dataclass(frozen=True, slots=True)
class CheckboxPatch:
    value: bool | None = None
    label: str | None = None
```

Each element type defines `def apply(self, patch: SliderPatch) -> SliderPatch`,
making the patch operation a method on the class. The wire format would
carry a discriminated union of patch types. Invalid field names become
a type error at the agent call site, not a silent no-op at the scene
manager.

This is a protocol-level change (wire format + agent SDK) and belongs
as a tracked design decision, not an ad-hoc refactoring.

### Typed element base with `id` as required field

`getattr(elem, "id", None)` in `scene/manager.py` should not exist.
Either:

- All elements have `id: str` as a required field on a typed base
  class or Protocol — then it's `elem.id` with no fallback.
- `id` is optional on some elements — then the type should reflect
  that with `id: str | None` as a proper field.

The `| None` fallback in `getattr` silently accepts elements with no
`id`, which then silently skip widget state sync. The correct behavior
is to make the presence or absence of `id` explicit in the type.

### Per-type deserializers

Each element kind's `from_dict` classmethod should handle all its own
fields — including `tooltip` if it applies — rather than a generic
post-hoc patch in the shared deserializer. The 27 element types each
know their own field set. The shared deserializer should do nothing
more than dispatch to the right `from_dict` by `kind`.

---

## Status

| Site | Fixed | Remaining debt |
|------|-------|---------------|
| tooltip stamping | `dataclasses.replace` | Per-type deserializer |
| field patching (`_apply_patch_set`) | `dataclasses.replace(**valid)` | Typed patches per element |
| scene_id stamping | `dataclasses.replace` | None |
| `getattr(elem, "id", None)` | Not yet | Typed `id` on Element base |
