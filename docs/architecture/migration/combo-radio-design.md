# Migration design: `combo` and `radio` onto the Element-ABC / Hub-Display path

**Status:** design for review. Beads `lux-qnyf` (combo), `lux-r2ay` (radio).
**Exemplar:** `checkbox` — the shipped atomic-selection interactive leaf.
**Ground truth:** [`target.md`](../target/target.md),
[`element-contract.md`](../target/element-contract.md),
[`migration/README.md`](./README.md), [DES-041](../../../DESIGN.md) (fork,
don't mix), [DES-051](../../../DESIGN.md) (additive ABC-kind registry).

## Abstract

`combo` (a dropdown, one selection from a list of items) and `radio` (a group of
radio buttons, one selection from a list of items) are the two remaining
**atomic-selection** interactive leaves. Both commit a *discrete* selection — an
index into `items` — exactly as `checkbox` commits a boolean. There is no
in-progress edit to reconcile: no `ContinuousEditArbiter`, no commit-on-idle, no
echo token. They are `checkbox` with an integer payload instead of a boolean.

This design migrates them together as one minimal family, preserving the legacy
element wire shape `{kind, id, label, items, selected}`, replacing the legacy
Display-local `WidgetState` reconciliation with the Hub-authoritative
read-`elem.selected`-each-frame pattern, and landing each kind additively through
the DES-051 registry. **No protocol change is required.**

## What I read (grounding by exemplar)

The `checkbox` atomic-selection path, end to end:

- **Element** — `protocol/elements/checkbox.py`. ABC subclass, keyword-only
  `__new__` with `RAISING_FACTORY` / `NO_EMIT` DI sentinels, read-only property
  surface, `_set_<field>` setters, `_remote_dispatch_specs` returning one
  `RemoteDispatchSpec(ValueChanged, "changed", "value_changed")`, `to_dict` /
  `from_dict` delegators, `widget_value`, `resolved_props`.
- **Codec** — `protocol/elements/checkbox_codec.py`. `JsonCheckboxDecoder`
  constructs the element, installs the built-in `_UpdateValueHandler`
  (`apply_patch({"value": event.value})` on `ValueChanged`), then installs any
  wire-declared handlers. `JsonCheckboxEncoder` is stateless `strip_none`.
- **Standalone handler builder** — `protocol/standalone_checkbox_handler.py`. A
  `noop` factory + `DecoratorRegistry` bound to the tier `PublishSink`.
- **ImGui adapter** — `display/renderers/imgui/checkbox.py`. A leaf:
  `begin` returns `True`, `paint` calls `er.checkbox_renderer.render(self._elem)`
  then `er.apply_tooltip`, `end` is a no-op.
- **Stateless renderer** — `display/renderers/checkbox_renderer.py`. Reads
  `elem.value` (the Hub-authoritative state) each frame; `imgui.checkbox` reports
  `changed` only on a genuine user click, giving **free echo-suppression** and
  **free idle-honour**; on a real toggle it `fire`s `ValueChanged` through the
  element's handler registry, which `DisplayServer._wrap_abc_elements` has wrapped
  for D21 remote dispatch.
- **Registry** — `protocol/elements/abc_kind_table.py` (one `LeafKindSpec` per
  kind), `abc_kind_names.py` (`MIGRATED_ABC_KINDS`), `abc_kind_verify.py`
  (`INTERACTIVE_KINDS`), `abc_leaf_spec.py`, `abc_registry.py`,
  `abc_kind_verify.py`.
- **D21 wire path** — `domain/event_handler_host.py`
  (`wrap_handlers_for_remote` iterates `_remote_dispatch_specs`, no `isinstance`
  branch), `domain/handlers/remote_dispatch.py` (`RemoteDispatchGroup` stamps the
  `RemoteEventHandlerInvocation`), `domain/hub/clients.py`
  (`_hub_interaction_dispatch` → `_typed_event` rebuilds the typed event on the
  Hub's authoritative copy and fires it once).
- **Legacy combo/radio** — `protocol/elements/combo.py`, `radio.py` (frozen
  dataclasses); `display/renderers/combo_renderer.py`, `radio_renderer.py`
  (`WidgetState`-driven, emit `RemoteEventHandlerInvocation` directly).
- **Reference migrations** — `slider.py` / `slider_codec.py` /
  `imgui/slider.py` and `tests/test_slider_migration.py`; the e2e harness
  `tests/e2e/scenario.py` + `tests/e2e/agent.py`.

### What crosses the boundary, in my own words

- **Hub-authoritative:** the element's `selected` index (and `items`, `label`,
  `tooltip`). The Hub's copy is the single source of truth.
- **Crosses IPC:** the pickled element replica (Hub → Display) and the
  `RemoteEventHandlerInvocation` carrying the new selected index (Display → Hub).
- **Display-local, never crosses:** the ImGui `combo` / `radio_button` draw
  calls. Under the ABC path there is **no** Display-local selection mirror — the
  legacy `WidgetState.ensure` cache is retired for these kinds; the widget is a
  pure function of `elem.selected` each frame.
- **Reconciliation:** an idle Hub re-push carrying the same `selected` re-paints
  the same widget state and fires nothing (ImGui reports `changed` only on a real
  click). A user selection fires exactly one `ValueChanged(value=<new index>)`.

## Design decision 1 — one PR, not two (minimal family)

**Recommendation: one PR, two commits (combo first, then radio), each with its
own migration-test file and each verified before the next.**

Rollback-granularity reasoning. `combo` and `radio` are structurally identical at
every layer that matters:

- the same wire shape `{kind, id, label, items: list[str], selected: int}`;
- the same value semantics (a discrete index into `items`);
- the same interaction (`ValueChanged`, action `"changed"`, kind
  `"value_changed"`, an `int` payload);
- the same reconciliation (read `elem.selected` each frame, no arbiter);
- the same `validate()` contract (index in range of `items`).

The one design decision they share — *"a single selection is an `int` index
carried on `value_changed`, reconciled the checkbox way"* — is the thing that
would be reverted if it proved wrong. If the int-index-on-`value_changed`
approach is mis-designed, **both** revert; that shared fate is the definition of
one rollback-coherent unit. They do not depend on each other, but they are not
independently-rollbackable concerns either — they are one concern applied twice.

This does not violate DES-041's "one element at a time." The migration README
scopes the per-element process to "every element **(or minimal family)**," and
`{combo, radio}` is precisely a minimal family: same fields, same value type,
same event. The verify-as-you-go discipline is preserved by sequencing within the
branch — combo is fully wired, Level-1–5-plus-e2e green, and operator-confirmed
before radio's commit begins. Two PRs would duplicate the review of an identical
design and split a single rollback unit for no benefit.

`selectable` is **not** in this family: its `selected` is a `bool` (a
toggle-in-a-list, nearer `checkbox`), not an index into `items`. It migrates
separately. So the "rule of three" tension does not arise here — there is no
shared abstraction to build (atomic kinds need no arbiter); there are only two
near-identical `checkbox` clones.

## Design decision 2 — value and wire shape

**The value is the selected index (`int`); the element wire shape is preserved
byte-for-byte for existing scenes.**

- **Element wire (Level 1 / `to_dict`):** `{kind, id, label, items, selected}`,
  where `selected` is the `int` index — identical to the legacy dataclass
  `to_dict`. Decode uses the same `ElementWireContext` helpers the legacy codec
  used (`optional_string_list("items")`, `optional_int_with_default("selected",
  0)`), so the wire contract is behaviour-preserving.
- **`widget_value()` stays the index** (`self._selected`), matching the legacy
  `ComboElement.widget_value` / `RadioElement.widget_value`.
- **Interaction payload (Display → Hub):** `ValueChanged(value=<selected
  index int>)`. The legacy renderers emitted a `{"index": i, "item": text}`
  **dict** as the `RemoteEventHandlerInvocation.value`. That dict is a legacy
  interaction-payload shape, **not** the element wire shape, and no consumer
  reads the `item` string (grep of `apps/`, `skills/`, `tools/` finds only
  doc-strings). The `item` is derivable from `items[selected]`, so the migrated
  path drops it and carries the scalar index — the shape `ValueChanged` and the
  Hub `_typed_event` already accept.

**One deliberate, behaviour-improving change to the wire (call it out in the PR):**
the legacy `combo`/`radio` `to_dict` **silently dropped `tooltip`** — the field
existed on the dataclass but was never serialized. The migrated encoder emits
`tooltip` through `strip_none`, exactly like `checkbox` and `slider`. Because
`strip_none` omits an absent (`None`) tooltip, the wire for every tooltip-less
combo/radio — which is the entire characterization corpus — is **identical** to
legacy; only a combo that actually carries a tooltip changes (from
silently-dropped to round-tripped). This is the "no pre-existing excuse" fix that
rides with the migration, and `make snapshot-parity` stays green on the existing
corpus.

## Design decision 3 — atomic reconciliation is the `checkbox` pattern, no arbiter

Confirmed: this is the `checkbox` model, not the `slider`/`input_text` model.

- **No `ContinuousEditArbiter`.** A selection has no in-progress intermediate
  state to reconcile against a racing Hub re-push. The commit is atomic — one
  click, one new index.
- **Idle re-push honours the Hub value.** The stateless renderer reads
  `elem.selected` each frame and passes it straight to `imgui.combo` /
  `imgui.radio_button`. A Hub re-push that changes `selected` is reflected on the
  next frame; a re-push carrying the same `selected` re-paints identically. This
  replaces the legacy `WidgetState.ensure(eid, initial)` mirror, which cached the
  first-seen value Display-side and therefore did **not** honour a later Hub
  re-push.
- **Exactly one `ValueChanged` per user selection.** `imgui.combo` returns
  `changed == True` only on a genuine user pick; `imgui.radio_button` returns
  `True` only on the frame the user clicks a not-currently-selected option (the
  legacy `and current != i` guard). Painting the Hub value programmatically never
  reports changed, so the fire → Hub → re-push → fire loop cannot form — the same
  free echo-suppression `checkbox` enjoys.

**Handler wiring (D21):**

1. The decoder installs a built-in `_UpdateSelectedHandler` on `ValueChanged`
   that runs `self._elem.apply_patch({"selected": event.value})` — the Hub-side
   state-sync, parallel to `_UpdateValueHandler`.
2. The element declares `_remote_dispatch_specs() ->
   (RemoteDispatchSpec(ValueChanged, self.action, "value_changed"),)` with
   `action == "changed"`. No new branch in `wrap_handlers_for_remote` — the
   inverted seam (DES-041 decision 5) iterates the spec.
3. On the Display, `_wrap_abc_elements` → `wrap_handlers_for_remote` collapses the
   `ValueChanged` bucket into one `RemoteDispatchGroup`. A user pick fires
   `ValueChanged(value=<index>)`; the group stamps one
   `RemoteEventHandlerInvocation(event_kind="value_changed", value=<index>)` to
   the Hub.
4. On the Hub, `_hub_interaction_dispatch` → `_typed_event` rebuilds
   `ValueChanged(value=<index>)` (the existing `value_changed` arm accepts any
   `bool | int | float | str`) and fires it once on the authoritative copy; the
   built-in handler applies `{"selected": <index>}` and the Hub re-pushes.

## Design decision 4 — the write-set per element

Each kind (`combo`, `radio`) gets the same seven-part write-set. The registry
seams are additive (DES-051); the fork-wiring seams remove the legacy path
(DES-041, fork-don't-mix — the new class keeps the canonical name).

**New / rewritten per kind:**

1. **Element class** — rewrite `protocol/elements/combo.py` (and `radio.py`)
   from a frozen dataclass to a `@final` ABC subclass. Keyword-only `__new__`
   with `RAISING_FACTORY` / `NO_EMIT` sentinels; read-only property surface
   (`id`, `kind`, `label`, `items`, `selected`, `action` → `"changed"`,
   `tooltip`); `_set_label` / `_set_items` / `_set_selected` / `_set_tooltip`
   setters; `apply_patch` override with a **whole-element boundary re-check**
   (like `slider.apply_patch`) because `selected`'s validity depends on `items`,
   so a combined `{"items": [...], "selected": n}` patch must be judged on final
   state and rolled back atomically if invalid; `_remote_dispatch_specs`;
   `validate()` (decision below); `to_dict` / `from_dict` delegators;
   `widget_value` (the index); `resolved_props`.
2. **Codec** — new sibling module `protocol/elements/combo_codec.py`
   (`radio_codec.py`): `JsonComboDecoder` (installs `_UpdateSelectedHandler`,
   then wire handlers via an `_install_handlers` mirror of the checkbox decoder),
   `JsonComboEncoder` (stateless `strip_none` over the five wire fields +
   `tooltip`). A per-codec `_UpdateSelectedHandler` class (serializable,
   `__reduce__` / `__setstate__`, `__call__` applies the `selected` patch),
   parallel to `_UpdateValueHandler`. Keeping the codec in its own module holds
   the element file under PY-OO-2 (≤ 300 lines, ≤ 3 classes).
3. **Standalone handler builder** — new
   `protocol/standalone_combo_handler.py` (`standalone_radio_handler.py`): a
   `noop` factory + `DecoratorRegistry`, parallel to
   `standalone_checkbox_handler.py`, returning `HandlerDecoder[ValueChanged]`.
4. **ImGui adapter** — new `display/renderers/imgui/combo.py`
   (`imgui/radio.py`): a `@final` leaf adapter, `begin` → `True`, `paint` →
   `er.combo_renderer.render(self._elem)` + `er.apply_tooltip(self._elem)`, `end`
   no-op — the `imgui/checkbox.py` shape verbatim.
5. **Stateless renderer rewrite** — rewrite
   `display/renderers/combo_renderer.py` (`radio_renderer.py`) to the
   `CheckboxRenderer` shape: drop the `WidgetState` / `EmitEventFn` constructor
   deps; read `elem.selected` each frame; on `changed` and a real index change,
   `elem.fire(ValueChanged(scene_id="__display__", element_id=elem.id,
   owner_id="__display__", value=<new index>))`. Keep the empty-`items` guard
   (`imgui.text(f"{label}: (empty)")`) and the horizontal `same_line` layout for
   radio.

**Additive registry seams (the DES-051 "one table entry" landing):**

1. `abc_kind_table.py` — two more `LeafKindSpec` entries in `_leaf_specs`, each
   with its `KindCodec(<Element>, Json<Kind>Decoder, Json<Kind>Encoder().encode)`
   and `handler_builder=build_standalone_<kind>_handler_decoder`.
2. `abc_kind_names.py` — add `"combo"`, `"radio"` to `MIGRATED_ABC_KINDS`.
   `abc_kind_verify.py` — add `"combo"`, `"radio"` to `INTERACTIVE_KINDS` (the
   hand-maintained witness that gives the import-time capability guard its teeth;
   omitting it lets a handler-less spec ship silently).

**Fork-wiring seams (remove the legacy path):**

1. `display/renderers/imgui/factory.py` — add `(ComboElement,
   ImGuiComboRenderer)`, `(RadioElement, ImGuiRadioRenderer)` to `_DISPATCH`.
2. `display/element_renderer.py` — remove `ComboElement` / `RadioElement` from
   `_NATIVE_DISPATCH`; remove `_combo_renderer` / `_radio_renderer` from
   `_WIDGET_STATE_RENDERERS`; construct the two stateless renderers with no deps
   (`ComboRenderer()`, `RadioRenderer()`), matching `CheckboxRenderer()`. The
   renderers stay owned by `ElementRenderer` and are reached by the ImGui adapter
   through a `combo_renderer` / `radio_renderer` property (as `checkbox_renderer`
   is).
3. Legacy `ElementCodec` registration — remove `combo` / `radio` from the legacy
   family-module `register_codecs` path so the migrated kinds leave the legacy
   codec table (the `slider` test asserts the migrated kind is absent from
   `build_element_codec().registered_kinds` while a still-legacy control
   remains). The negative control for these PRs is `selectable`.

**Shared boundary utility (one small additive method):**

1. `PatchField.as_int` — `combo`, `radio` (and later `selectable`'s bool aside)
   need an integer index coercion the class does not yet expose (it has
   `as_bool` / `as_number` / `as_str`). Add `as_int`: reject `bool` (a subclass
   of `int`) and reject non-`int` (an index must be an exact whole number, not a
   truncated float), raising `TypeError` naming the field. This is a legitimate
   shared boundary coercer on the class that already owns the others (PY-OO-5),
   not a free function.

## Design decision 5 — protocol touch: none

**No `ValueChanged.value` union widening, and no new `InteractionEventBuilder`
arm.**

- `ValueChanged.value` is already `bool | int | float | str`
  (`domain/interaction.py`). A selection index is an `int` — it rides the
  existing arm. The docstring's per-kind list (`checkbox→bool`, `input_text→str`,
  …) gains `combo`/`radio`→`int`, but the type does not change.
- The Hub dispatch `_typed_event` (`domain/hub/clients.py`) already accepts any
  scalar for `value_changed` and rejects non-scalars — an `int` index is accepted
  with no code change.
- `InteractionEventBuilder` (`domain/interaction_event_builder.py`) is the
  in-process `Display.interact` double and only knows `checkbox` / `input_text` /
  `collapsing_header` / `tab_bar`. It does **not** cover `slider` /
  `input_number` / `color_picker` — which are migrated and green — because the
  production and e2e-harness dispatch flows through `clients.py`, not through this
  double. `combo` / `radio` therefore need **no** arm here; adding one would be
  dead surface.

The interaction contract in `element-contract.md` is satisfied as-is: `event_kind
= "value_changed"`, `action = "changed"`, `value` carries the new selection —
the value-changing shape the doc prescribes.

## Validation contract per kind (DES-039, rides with the migration)

`validate()` returns component-appropriate errors; the tree walk accumulates them
and an invalid tree is never rendered. For `combo` and `radio` the invariant is
**the selected index must address a real item**:

- `selected` must be `>= 0` — a negative index is never valid.
- if `items` is non-empty, `selected` must be `< len(items)`.
- if `items` is empty, `selected` must be `0` — the only meaningful value for an
  itemless (deferred-population) combo/radio; any other index is a data mistake.
- `items` cells are strings — already enforced at decode by
  `optional_string_list`; the ABC re-check is unnecessary beyond the decode
  boundary.

No fail-fast: collect every error (both the range checks can only produce one at
a time here, but the walk still aggregates across the hierarchy). The legacy
renderers *silently clamped* an out-of-range index to `0` and logged a warning —
that is exactly the silent-accept-invalid class DES-039 closes. The migrated kind
**reports** it so the agent fixes its data and re-shows.

## BEFORE / AFTER — how `combo` lands as one table entry

**BEFORE** (legacy): `combo` is a frozen dataclass on the `SceneManager` +
dual-write path; its renderer mirrors state into `WidgetState` and emits a
`RemoteEventHandlerInvocation` dict directly; it is registered in the legacy
`ElementCodec` family module and dispatched by `ElementRenderer._NATIVE_DISPATCH`.

**AFTER** (migrated) — the additive registry surface is three edits:

```python
# abc_kind_table.py  —  _leaf_specs(), one entry per kind
LeafKindSpec(
    kind="combo",
    codec=KindCodec(ComboElement, JsonComboDecoder, JsonComboEncoder().encode),
    handler_builder=build_standalone_combo_handler_decoder,
),

# abc_kind_names.py  —  MIGRATED_ABC_KINDS
frozenset({..., "combo", "radio"})

# abc_kind_verify.py  —  INTERACTIVE_KINDS
frozenset({..., "combo", "radio"})
```

The factory, encoder dispatch, and container gate do not change — they read the
registry. The import-time `AbcKindVerifier` now **requires** `combo`/`radio` to
carry the `HANDLERS` capability, so forgetting the `handler_builder` fails loud at
import rather than shipping a handler-less combo. The corresponding fork-wiring
edits remove the legacy dispatch/codec entries in the same PR (fork-don't-mix; no
two live paths for one kind).

## Verification plan

Per-kind migration-test files `tests/test_combo_migration.py` and
`tests/test_radio_migration.py`, modelled on `tests/test_slider_migration.py`,
covering the round-trip procedure in `tests/CLAUDE.md`:

- **Level 1 — serialization roundtrip:** build → `to_dict` → `from_dict` → assert
  equal; assert the wire is exactly `{kind, id, label, items, selected}` for a
  tooltip-less element (byte-parity with legacy); assert `tooltip` round-trips
  when present; assert the migrated kind is **absent** from
  `build_element_codec().registered_kinds` with `selectable` as the still-legacy
  control.
- **Self-validation (DES-039):** valid element → `validate() == ()`; out-of-range
  `selected` → one error naming the element; itemless combo with `selected != 0`
  → one error; drive an invalid combo/radio through `show()` and assert
  `client.show.assert_not_called()`; assert nested-in-`group` **and** nested-in-a
  second container are collected by the walk.
- **Level 2 — wire roundtrip:** the ABC element crosses a `SceneMessage` as a
  `_pickled` entry; assert the built-in `_UpdateSelectedHandler` survives
  (`handler_count(ValueChanged) == 1`).
- **Level 3 — Hub/Display crossing + rebind:** `_wrap_abc_elements` binds the
  `ImGuiRendererFactory` onto the element; `render_path == "abc"`.
- **Level 4 — interaction roundtrip / D21 (the standing gate):** add one
  `Scenario` value to `tests/e2e/scenario.py` (a `group` holding a publishing
  combo/radio beside a display-only `progress`), a shared commit constant
  (e.g. `COMBO_COMMIT_INDEX = 1`) with `InteractionExpectation(event_kind=
  "value_changed", value=1)` and `PropAfterDispatch(field="selected", value=1,
  flipped=True)`, plus one `isinstance` branch in `tests/e2e/agent.py`
  `_event_for` firing `ValueChanged(value=<index>)`. The harness fires the
  replica's own wrapped handler over the real `InMemoryConnection`, proving the
  full loop: **one** commit on selection crosses the faithful boundary, the real
  handler runs **once** on the Hub's authoritative copy, the business event a real
  subscriber receives is published, the agent reacts, and the re-push reflects the
  new `selected` (invariants I1–I6). A companion unit test asserts a **Hub-driven**
  `apply_patch({"selected": n})` fires **no** invocation (idle-honour), and a real
  `fire` emits **exactly one** carrying the int — the `slider` test's
  `TestInteraction` pattern.
- **Level 5 — introspection:** `inspect_scene` reports `render_path == "abc"` and
  `resolved_props` reads back `{label, items, selected, tooltip}` including
  defaults.
- **Capability guard now covers the kind:** a test (or the existing
  `AbcKindVerifier` import-time check) asserts that removing the
  `handler_builder` for combo/radio raises at registry build — the guard proves
  the interactive kind cannot ship handler-less.
- **Snapshot parity:** `make snapshot-parity` stays green (tooltip-less wire is
  byte-identical to legacy).
- **Level 6 — manual visual confirmation:** `make restart`, render a combo and a
  radio live, pick an option, capture `inspect_scene` / `list_recent_events`, and
  get operator confirmation that the selection round-tripped and the Hub value
  updated once. (Operator-confirmed, per the demo-and-design discipline.)

## OO rules in scope

- **PY-OO-5 (data + behavior on the class):** the codec is classes-with-methods
  (`JsonComboDecoder.decode`, `JsonComboEncoder.encode`, `_UpdateSelectedHandler`)
  — no module-level `_combo_to_dict(m)` / `_combo_from_dict(d)` functions; the
  index coercion is `PatchField.as_int`, a method on the class that owns the
  other coercers, not a free helper.
- **PY-OO-2 (≤ 300 lines, ≤ 3 classes per module):** the element and its codec
  live in separate modules (`combo.py` + `combo_codec.py`), as `checkbox` /
  `slider` do, so neither file breaches the limits and no rebaseline-to-absorb
  growth is needed.
- **Protocol, not base class:** each spec satisfies the structural
  `AbcKindSpec` Protocol via `LeafKindSpec`; the element satisfies both the
  behavioral `Element` ABC and the structural `domain.element.Element` Protocol
  (`to_dict` / `from_dict` / `kind` / `id`). No new base class.
- **Literal over `str`-with-comment:** `kind` is `Literal["combo"]` /
  `Literal["radio"]`; `action` is `Literal["changed"]`. There is no mode field
  requiring a `Literal` here (`items`/`selected` are genuinely open data), but the
  discriminators are typed.
- **Reduce `| None` (PY-TS-14):** the only Optional is `tooltip: str | None`,
  which stays — absence is the documented contract for "no tooltip," the same
  justification `checkbox`/`slider` carry. `selected` is a total `int` (default
  `0`), not an Optional; `items` is a total `list[str]` (default empty), not an
  Optional.
- **PY-IC-2 `@final`:** the element, codec, and adapter classes are leaves and
  are marked `@final`.

## Escalation to the leader

No substantive design deviations. The three points worth an explicit ruling
before dispatch:

1. **One PR (minimal family), combo-first-then-radio** — recommended above.
2. **Drop the legacy `{"index","item"}` interaction dict; carry the scalar
   index** on `value_changed` — recommended (no consumer reads `item`; the Hub
   recomputes it from `items[selected]`).
3. **Serialize `tooltip` (the behaviour-improving wire fix)** that legacy
   silently dropped — recommended (snapshot-parity-safe; matches every other
   migrated interactive leaf).

All three are the low-risk, standards-aligned reading; none opens a new contract
surface. Implementation is ready to dispatch on ratification.
