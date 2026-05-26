# Lux Python OO Standard

**Status:** mandatory coding standard for Lux runtime code.

This is an implementation standard, not an architecture document.

Lux is an authoritative, retained, event-driven UI system with replicated
state, handler dispatch, ownership rules, and business-logic fan-out. For
this use case, **object-oriented Python is the only approved implementation
paradigm**. Procedural glue around passive dataclasses is not acceptable for
core runtime paths.

## Scope

This standard applies to production Python in `src/punt_lux/`, and to tests
that define or exercise runtime seams.

It applies especially to:

- domain objects
- protocol/message/element types
- Hub and Display coordination
- handler dispatch
- state mutation and validation paths

It does not mean every helper must become a class. Pure formatting helpers,
small utilities, and wiring code can remain functions when they are genuinely
stateless.

## Non-Negotiable Rules

1. **Classes own data and behavior.**
   If a type has meaningful state and meaningful behavior, the behavior belongs
   on the class. Runtime code must not devolve into module-level functions that
   operate on passive records.

2. **Typed boundaries, loud failures.**
   Boundary validation must happen at decode/dispatch edges, and failures must
   be explicit. No silent defaults that mask bad input. No best-effort schema
   guessing in domain code.

3. **No dynamic attribute access in runtime paths.**
   `getattr`, `setattr`, and `hasattr` are design smells in Lux runtime code.
   If a path needs them, the type model is underspecified and must be improved.

4. **Prefer composition, protocols, and small value types.**
   Shared behavior should come from protocols, composition, and focused helper
   types, not inheritance trees full of shared mutable state.

5. **Avoid open-ended string vocabularies.**
   Do not use `str` plus comments to represent closed sets of values. Use
   `Literal[...]`, enums when appropriate, or typed verb vocabularies.

6. **Reduce optionality aggressively.**
   `| None` is not a default style. Use it only when absence is a real domain
   state. Otherwise model the state explicitly.

7. **Behavior lives on the authoritative side.**
   If behavior is authoritative, it belongs on Hub-side runtime objects. The
   Display may render and forward interactions, but it does not become a second
   authority.

8. **No dead infrastructure.**
   New abstractions must land with a real consumer. Do not add speculative
   frameworks, registries, or migration scaffolding with no production use.

9. **No long-lived shims.**
   Compatibility glue may exist only within the change that fully replaces an
   old path. Lux does not keep parallel "old and new" implementations around as
   a steady state.

10. **Tests land with the code.**
    Every user-visible runtime change must ship with tests in the same change.

## What This Means In Practice

Bad:

```python
@dataclass
class Button:
    id: str
    label: str


def button_to_dict(button: Button) -> dict[str, object]:
    return {"kind": "button", "id": button.id, "label": button.label}
```

Good:

```python
class ButtonElement:
    def to_dict(self) -> dict[str, object]:
        return {"kind": "button", "id": self.id, "label": self.label}
```

Bad:

```python
for key, value in patch.items():
    if hasattr(obj, key):
        setattr(obj, key, value)
```

Good:

```python
def apply_patch(self, patch: Mapping[str, object]) -> Self:
    for key, value in patch.items():
        setter = getattr(self, f"_set_{key}", None)
        if setter is None:
            raise AttributeError(...)
        setter(value)
    return self
```

The "good" example is acceptable because the dynamic lookup stays inside the
class's own typed patch mechanism. Callers do not reflect over foreign objects.

Bad:

```python
kind = raw.get("kind", "text")
```

Good:

```python
kind = raw.get("kind")
if not isinstance(kind, str) or not kind:
    raise ValueError("Element missing or invalid 'kind' field")
```

## Enforcement

This standard is enforced, not aspirational.

- `make check` must pass before a change is considered done.
- `make check` includes the OO ratchet via `make check-oo`.
- Touched code must not regress OO metrics.
- After improving the code, update the ratchet baselines with
  `make update-oo`.
- Do not edit `.oo-baseline.json` by hand.
- Do not suppress the ratchet instead of fixing the code.

If a change would require regressing the OO standard, the design is wrong and
must be reconsidered.

## Relationship To Other Rules

This file is the repo-level standard for Lux.

It complements:

- `punt-labs/.claude/rules/python-*.md` — org-wide Python rules
- [../architecture/target/target.md](../architecture/target/target.md) — the
  rewrite target
- [../architecture/target/ui-model.md](../architecture/target/ui-model.md) —
  the authoritative UI model the code is moving toward

When in doubt:

- architecture docs say **what Lux is trying to become**
- this standard says **how Lux code must be written**
