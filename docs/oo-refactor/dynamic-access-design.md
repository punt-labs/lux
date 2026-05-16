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
