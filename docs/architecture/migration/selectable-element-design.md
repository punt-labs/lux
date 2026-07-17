# Migrating `selectable` onto the Element-ABC / Hub-Display path

**Bead:** lux-07f5 · **Epic:** lux-xs7r · **Kind:** design (no code)
**Exemplar:** `checkbox` (bool-atomic) · **Siblings:** `combo` / `radio` (DES-052)

`selectable` is the fourth atomic interactive leaf and the simplest of them.
Its value is a `bool` on/off toggle — it is a `checkbox` that paints as a
list row via `imgui.selectable` instead of `imgui.checkbox`. It carries no
index-into-`items` (that is `combo` / `radio`), so there is no cross-field
invariant, no `apply_patch` override, and — being atomic — no
`ContinuousEditArbiter`. It is the payoff case for the shared value handler
the combo/radio dedup set up: it reuses `ApplyPatchOnChange` with **zero**
new handler code.

## What I read (grounding, end-to-end)

Bool-atomic exemplar:

- `protocol/elements/checkbox.py` — `@final`-shaped ABC leaf; `_value: bool`,
  keyword-only `__new__` with `abc_di_defaults` sentinels, property `value`,
  `_set_value` via `PatchField("value").as_bool`, `_remote_dispatch_specs`
  → `RemoteDispatchSpec(ValueChanged, "changed", "value_changed")`,
  `to_dict`/`from_dict` delegators, `widget_value`, `resolved_props`. No
  `validate()` override — no `apply_patch` override.
- `protocol/elements/checkbox_codec.py` — `JsonCheckboxDecoder` installs
  `ApplyPatchOnChange(elem, field="value")` then wire `handlers`;
  `JsonCheckboxEncoder.encode` = `strip_none({kind,id,label,value,tooltip})`.
- `display/renderers/imgui/checkbox.py` — `ImGuiCheckboxRenderer` adapter
  (`begin`→True, `paint`→`er.checkbox_renderer.render(elem)` + `apply_tooltip`,
  `end` no-op).
- `display/renderers/checkbox_renderer.py` — stateless `CheckboxRenderer`:
  reads `elem.value` each frame, `imgui.checkbox` returns `(changed, value)`,
  fires `ValueChanged(value=value)` on a genuine toggle; echo-suppression is
  free (painting the Hub value leaves `changed` False).

Atomic-selection siblings (the shared handler):

- `protocol/elements/value_change_handlers.py` —
  `type ChangedField = Literal["value", "selected"]`; `@final`
  `ApplyPatchOnChange(elem, *, field: ChangedField)` calls
  `elem.apply_patch({field: event.value})`, pickle-safe;
  `@final NoopValueHandler`; `build_standalone_value_handler_decoder(sink)`.
  **The `"selected"` arm already exists** — combo/radio use it.
- `protocol/elements/combo.py` / `combo_codec.py` — the int-index sibling;
  read for the atomic pattern and to confirm `selectable` is *simpler* (no
  index invariant, so no `apply_patch`/`validate` overrides, no
  `_index_error_messages`).

DES-051 registry (the "one file a migration edits"):

- `protocol/elements/abc_kind_table.py` — `DefaultAbcKinds._leaf_specs()`;
  a leaf spec is one `LeafKindSpec(kind=..., codec=KindCodec(...),
  handler_builder=build_standalone_value_handler_decoder)`.
- `protocol/elements/abc_kind_names.py` — `MIGRATED_ABC_KINDS` frozenset.
- `protocol/elements/abc_kind_verify.py` — `INTERACTIVE_KINDS` frozenset; the
  capability guard raises if an interactive kind's spec omits `HANDLERS`.
- `abc_kind_spec.py` / `abc_leaf_spec.py` — the `AbcKindSpec` Protocol
  (structural, `runtime_checkable`) and the `LeafKindSpec` shape.

Legacy `selectable` (what it emits today):

- `protocol/elements/selectable.py` — `@dataclass(frozen=True, slots=True)`,
  `selected: bool = False`, `tooltip: str | None = None`. `to_dict` emits
  `{kind,id,label}` and adds `selected: True` **only when True**; **never
  emits `tooltip`**. `from_dict` reads `id/label/selected` (not tooltip).
- `display/renderers/selectable_renderer.py` — legacy renderer holding
  `WidgetState` + `EmitEventFn`; `imgui.selectable(label, current)` →
  `(clicked, new_val)`; on click writes `WidgetState` and emits a
  `RemoteEventHandlerInvocation(action="clicked", value=new_val)` directly.
  This is the legacy pump path the migration retires.
- Registration / dispatch touchpoints: `protocol/elements/inputs.py`
  (`InputsRegistry` — selectable is its *only* remaining registration);
  `display/element_renderer.py` `_NATIVE_DISPATCH` (DES-042) +
  `_WIDGET_STATE_RENDERERS`; `display/renderers/imgui/factory.py` `_DISPATCH`;
  `display/server.py:1026` `_auto_click_emit_loop` selectable branch.

Docs + gate: `migration/README.md` (DES-041 fork-don't-mix; DES-042
transitional leaf compatibility; verify-as-you-go), `combo-radio-design.md`,
`target/element-contract.md`, `tests/CLAUDE.md` (Levels 1-6),
`tests/test_combo_migration.py` (the gate template).

## The boundary, restated

- **Hub-authoritative:** `selected: bool`, `label`, `tooltip`. The Hub decodes
  the wire once, installs the `SelectableElement` in `HubDisplay`, and runs the
  real handler. `ApplyPatchOnChange(field="selected")` mirrors a toggle onto
  the authoritative `_selected` when `ValueChanged` fires on the Hub copy.
- **Crosses the wire:** the pickled `SelectableElement` (Hub→Display replica)
  and, back, the `RemoteEventHandlerInvocation` a display click produces after
  `wrap_handlers_for_remote` wraps the replica's handler.
- **Display-local:** the `imgui.selectable` call and its pixels. The stateless
  `SelectableRenderer` reads `elem.selected` each frame and holds no per-scene
  state; a genuine click fires `ValueChanged(value=new_val)`, the Display
  forwards it to the Hub, the Hub re-dispatches on its copy and re-pushes.

`selectable` maps onto `checkbox` field-for-field, substituting the wire key
`selected` for `value` and `imgui.selectable` for `imgui.checkbox`.

## Design answers to the mission's questions

1. **Value is `bool`.** Confirmed against `selectable.py` (`selected: bool`)
   and the legacy renderer (`imgui.selectable(label, current) -> (clicked,
   new_val)`, `new_val` a bool). `imgui.selectable` fires on click exactly as
   `imgui.checkbox` fires on toggle — same `(changed, value)` shape.
2. **Wire.** Preserve the legacy `selectable` wire: key `selected` (bool). It
   rides the existing `ValueChanged.value` bool arm — **no protocol touch, no
   change to `value_change_handlers.py`.**
3. **Reconciliation = the checkbox pattern.** Stateless renderer reads
   `elem.selected` each frame; one `ValueChanged` per click; echo-suppression
   is free (painting the Hub value leaves `changed` False); no arbiter. Reuse
   the shared `ApplyPatchOnChange(elem, field="selected")` +
   `build_standalone_value_handler_decoder` — the general solution, no bespoke
   handler.
4. **`validate()` is vacuous → no override.** A `bool` toggle plus a `str`
   label is always well-formed; there is no `selected`-vs-`items` range to
   police (that is combo/radio). Like `checkbox`, `SelectableElement` inherits
   the ABC default `validate() -> ()` (`domain/element_abc.py:167`). DES-039 is
   satisfied by the *component-appropriate* answer being "no constraints." The
   self-validation **tests** still exist — `validate() == ()` for a valid
   element, and malformed **wire** (missing `id`, non-bool `selected`) rejected
   at the codec boundary (PY-EH-1), driven through `show()` with
   `client.show.assert_not_called()`, including nested-in-`group` and
   nested-in-`collapsing_header`.
5. **Write-set** below.
6. **Ride-alongs:** tooltip round-tripping (the legacy `to_dict` silently
   dropped it — mirror combo/radio's fix). No reject-not-clamp fix applies:
   there is nothing to clamp on a bool.

## Write-set

The specialist owns final decomposition; this is the surface the design
implies. Every module stays under PY-OO-2 (≤ 300 lines, ≤ 3 classes).

### New (2)

- `src/punt_lux/protocol/elements/selectable_codec.py` —
  `JsonSelectableDecoder` + `JsonSelectableEncoder`, mirroring
  `checkbox_codec.py`. Decoder installs
  `ApplyPatchOnChange(elem, field="selected")` then any wire `handlers`;
  encoder emits `{kind,id,label}` + `selected` + `tooltip` per the emit policy
  ratified in Decision 2/3.
- `src/punt_lux/display/renderers/imgui/selectable.py` —
  `@final ImGuiSelectableRenderer`, a byte-for-byte analogue of
  `imgui/checkbox.py` (`paint` → `er.selectable_renderer.render(elem)` +
  `apply_tooltip`).

### Rewritten (2)

- `src/punt_lux/protocol/elements/selectable.py` — frozen dataclass → `@final`
  ABC `SelectableElement` (PY-CC-1 `__new__`, PY-IC-2 `@final`, PY-EN-1/2
  `_selected` + property). Fields `_id/_label/_selected/_tooltip/_kind`;
  keyword-only `__new__` with `RAISING_FACTORY`/`NO_EMIT` sentinels; property
  `selected`; `action -> Literal["changed"]`; `_set_selected` via
  `PatchField("selected").as_bool`; `_remote_dispatch_specs` →
  `(RemoteDispatchSpec(ValueChanged, "changed", "value_changed"),)`;
  `to_dict`/`from_dict` delegators (`from_dict` wires
  `build_standalone_value_handler_decoder` + `RaisingPublishSink`);
  `widget_value -> bool`; `resolved_props`. **No** `validate()` override,
  **no** `apply_patch` override. The canonical name stays `SelectableElement`
  (leaf; no composite forces a `Legacy*` twin, so none is created).
- `src/punt_lux/display/renderers/selectable_renderer.py` — WidgetState +
  `EmitEventFn` renderer → stateless `SelectableRenderer` mirroring
  `checkbox_renderer.py`: `__new__()` takes no args, `render(elem)` reads
  `elem.selected`, `imgui.selectable(f"{label}##{id}", elem.selected)`, on
  `clicked` fires `elem.fire(ValueChanged(..., value=new_val))`. Drops the
  direct `RemoteEventHandlerInvocation` emit — D21 wrapping owns that now.

### Additive edits (registry + display dispatch)

- `abc_kind_table.py` — import `SelectableElement`, `JsonSelectableDecoder`,
  `JsonSelectableEncoder`; add one `LeafKindSpec` in `_leaf_specs()`.
- `abc_kind_names.py` — add `"selectable"` to `MIGRATED_ABC_KINDS`.
- `abc_kind_verify.py` — add `"selectable"` to `INTERACTIVE_KINDS`.
- `display/renderers/imgui/factory.py` — import `ImGuiSelectableRenderer` +
  `SelectableElement`; add `(SelectableElement, ImGuiSelectableRenderer)` to
  `_DISPATCH`.
- `display/element_renderer.py` — `self._selectable_renderer =
  SelectableRenderer()` (drop args); **remove** `"_selectable_renderer"` from
  `_WIDGET_STATE_RENDERERS` (it holds no per-scene state now); **keep**
  `(SelectableElement, "_selectable_renderer")` in `_NATIVE_DISPATCH`
  (DES-042 — a legacy container holding an ABC leaf still paints it); add a
  `selectable_renderer` property (mirror `combo_renderer`).

### Fork-wiring removals

- `src/punt_lux/protocol/elements/inputs.py` — **delete the module.**
  `selectable` was `InputsRegistry`'s only remaining registration; once it
  moves to the ABC registry the class is empty. Remove the `InputsRegistry`
  import and the `InputsRegistry().apply(codec.register)` call from
  `protocol/elements/__init__.py` (`build_element_codec`). PL-PP-1: no dead
  shim, no empty-class tombstone.
- `display/server.py:1026` `_auto_click_emit_loop` selectable branch — this
  synthetic auto-click harness switches on `isinstance(elem,
  SelectableElement)` and still functions against the ABC class (`not
  elem.selected`). The combo/radio branches were left untouched on their
  migration; **recommend leaving this branch as-is** (behavior-preserving,
  orthogonal to the Level-4 harness, which fires the replica's own wrapped
  handler). Flagged, not changed.

### Tests

- **New** `tests/test_selectable_migration.py` — the combo gate, minus the
  index machinery. Levels 1-5 + capability guard + malformed-wire rejection +
  self-validation + interaction + fork gate:
  - **L1:** roundtrip; wire-shape assertion per the emit policy; tooltip
    round-trips; absent tooltip stays `None`; absent from the legacy
    `ElementCodec` table.
  - **Capability guard:** `"selectable"` in `MIGRATED_ABC_KINDS` +
    `INTERACTIVE_KINDS`; a handler-less selectable spec fails
    `_verify_capabilities`.
  - **Malformed wire:** missing `id` rejected; non-bool `selected` rejected;
    non-list `handlers` rejected.
  - **Self-validation:** `validate() == ()` for valid; `isinstance(_, AbcElement)`;
    `child_elements() == ()`; passes the tree walk; `show()` rejects a
    malformed selectable and rejects it nested in `group` and
    `collapsing_header` (`client.show.assert_not_called()`).
  - **Patch path:** `apply_patch({"selected": True})` advances in place and
    returns `self` (no range invariant, so no rollback-on-range case).
  - **L2:** crosses as a `_pickled` scene entry; the built-in state-sync
    handler survives (`handler_count(ValueChanged) == 1`).
  - **L3:** `_wrap_abc_elements` rebinds the ImGui factory onto the replica.
  - **Interaction:** the built-in handler syncs `selected` on the Hub copy;
    a Hub-set value does **not** refire; a genuine `fire` emits exactly one
    invocation with `event_kind == "value_changed"` and a bool `value`.
  - **L5:** `render_path == "abc"`; `resolved_props` reads back
    `{label, selected, tooltip}` including defaults.
- Move the three legacy selectable wire tests out of
  `test_inputs_migration.py` into the new file (they exercise the ABC path
  now): `test_selectable_omits_selected_when_false` /
  `test_selectable_emits_selected_when_true` (line 237/243) and
  `test_selectable_rejects_non_bool_selected` (line 426). Under Decision 2b
  they pass unchanged.
- Repoint the "still-legacy negative control" from `"selectable"` to another
  still-legacy kind (`"tree"` / `"spinner"`): `test_combo_migration.py:123`,
  `test_radio_migration.py:123`, `test_inputs_migration.py:174`.
- The AST "no module-level codec helpers" guard (`test_inputs_migration.py`
  line ~340) already lists `"selectable"` — it passes once the codec lives in
  `selectable_codec.py`. Keep it.
- **Level-4 e2e:** add a `selectable` `Scenario` value to `tests/e2e/`
  (one value, not new assertion code — per `tests/CLAUDE.md` §Level 4).

### Docs

- `docs/architecture/element-migration-audit.md` — flip `selectable` to the
  ABC path.
- `docs/architecture/migration/README.md` — bump the migrated list/count.

## BEFORE / AFTER — registration

**`abc_kind_names.py`** (`MIGRATED_ABC_KINDS`):

```text
  "combo",
  "radio",
+ "selectable",
  "group",
```

**`abc_kind_verify.py`** (`INTERACTIVE_KINDS`):

```text
  "combo",
  "radio",
+ "selectable",
  "dialog",
```

**`abc_kind_table.py`** (`_leaf_specs()`, after the `radio` entry):

```python
LeafKindSpec(
    kind="selectable",
    codec=KindCodec(
        SelectableElement, JsonSelectableDecoder, JsonSelectableEncoder().encode
    ),
    handler_builder=build_standalone_value_handler_decoder,
),
```

**`display/renderers/imgui/factory.py`** (`_DISPATCH`, after `radio`):

```python
(RadioElement, ImGuiRadioRenderer),
+ (SelectableElement, ImGuiSelectableRenderer),
```

**`display/element_renderer.py`** — construction, widget-state set, and
native dispatch:

```python
# BEFORE
self._selectable_renderer = SelectableRenderer(widget_state, emit_event)
_WIDGET_STATE_RENDERERS = (..., "_selectable_renderer", "_container_renderer")

# AFTER
self._selectable_renderer = SelectableRenderer()
_WIDGET_STATE_RENDERERS = (..., "_container_renderer")   # selectable removed
# _NATIVE_DISPATCH keeps (SelectableElement, "_selectable_renderer")  — DES-042
# NEW: `selectable_renderer` property mirroring `combo_renderer`
```

## The shared handler reuse (the payoff)

`ApplyPatchOnChange`'s `field` names the element's own patch field, **not** a
fixed literal. `ChangedField = Literal["value", "selected"]` already carries
`"selected"` (combo/radio's arm), so:

```python
elem.add_handler(ValueChanged, ApplyPatchOnChange(elem, field="selected"))
```

works with **zero** change to `value_change_handlers.py`. A bool
`ValueChanged.value` flows through `apply_patch({"selected": bool})` →
`_set_selected` (`PatchField("selected").as_bool`). `selectable` is the third
consumer of the shared handler that the combo/radio dedup was built for — no
per-kind arbiter, no new handler module.

> **Note on the mission's parenthetical.** The brief suggested
> `ApplyPatchOnChange(field="value")`. That would rename the wire key
> `selected` → `value`, breaking wire compatibility and contradicting the
> "preserve the legacy wire / no protocol touch" directive. The wire-preserving
> wiring is `field="selected"` (Decision 1). Either literal reuses the shared
> handler identically; only `"selected"` keeps the wire.

## PR granularity

**`selectable` alone = one PR** (one rollback-coherent unit). It touches no
other kind: the registry edits are additive, the removals are its own legacy
wiring, and the negative-control test repoints are mechanical. Nothing else
rolls back with it.

## Verification plan

Per `tests/CLAUDE.md` and `migration/README.md` verify-as-you-go:

1. **`make check`** green (ratchet included; `selectable.py` moves from a
   procedural dataclass to an ABC class — method_ratio and encapsulation
   improve; the codec split keeps both files ≤ 300 lines). Stage
   `.oo-baseline.json` + `.oo-audit.jsonl` in the same commit.
2. **Levels 1-5 + capability guard** in `test_selectable_migration.py` against
   the real boundary (never a stub).
3. **Level-4** via the `tests/e2e/` business-event-loop harness — a
   `selectable` `Scenario`: injected toggle crosses the faithful
   `InMemoryConnection`, the real handler runs once on the Hub's `HubDisplay`
   copy, the re-push reflects the flipped `selected`.
4. **`make restart`**, then drive a live `selectable` through `show()`,
   click it in the window, and confirm via introspection (`inspect_scene`
   → `render_path == "abc"` + `resolved_props.selected` flipped;
   `list_recent_events` shows the `value_changed`). **Operator confirms Level 6.**
   - Expected, written before running: a two-row selectable scene renders as
     clickable list rows; clicking row A sets its `selected` True on the Hub
     copy and the re-push shows it highlighted; `render_path == "abc"`.
   - Boundary/negative: `show()` a selectable with `selected: "yes"` → rejected
     (`error: scene not rendered`, `[selectable 'id']`), `client.show`
     never called; a selectable nested in an all-ABC `group` renders.

## OO rules in scope

- **PY-OO-2** — `selectable.py` and `selectable_codec.py` each one class,
  ≤ 300 lines; the codec split keeps the element file small.
- **PY-OO-5 / PY-OO-7** — codec is `to_dict(self)` / `from_dict(cls)` on/for
  the class via the encoder/decoder objects; no module-level
  `_selectable_to_dict` helpers (the AST guard enforces this).
- **PY-TS-6** — `SelectableElement` satisfies the `Element` / `AbcKindSpec`
  Protocols structurally; no new base class.
- **PY-CC-1 / PY-IC-2** — `__new__` constructor; `@final` leaf.
- **PY-TS-8** — `kind: Literal["selectable"]`, `action: Literal["changed"]`;
  no `str`-with-comment.
- **PY-TS-14 / PY-EN-1/2** — `_selected` private + read-only property;
  `tooltip: str | None` is the one justified Optional (absence = no tooltip,
  the documented contract — matches checkbox).
- **PY-EH-1** — validate at the codec boundary (`ElementWireContext`), trust
  internally.

## Decisions — ratified by the operator

**Decision 1 — wire field name (load-bearing). RATIFIED: `selected` (bool).**
Wire `ApplyPatchOnChange(elem, field="selected")`. Preserves the legacy wire
key, touches no protocol, reuses the shared handler unchanged. (Supersedes the
initial `field="value"` framing, which would have broken the wire.)

**Decision 2 — encoder emit policy. RATIFIED: always emit `selected` (2a).**
The encoder emits `selected` unconditionally (via `strip_none` over the bool —
no omit-when-false conditional). Design is not written to match legacy
behavior; correctness wins — an unselected row still states `selected: false`.
The legacy pinning test `test_selectable_omits_selected_when_false` is flipped
to `test_selectable_always_emits_selected`; snapshot corpus updates for
unselected rows are expected, not a regression.

**Decision 3 — tooltip round-tripping. RATIFIED: yes.** The legacy `to_dict`
silently dropped `tooltip`; this migration round-trips it (encode via
`strip_none`, decode via `optional_nullable_str`), mirroring combo/radio.
