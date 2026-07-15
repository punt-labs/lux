# Element migration: `slider` onto the Element-ABC / Hub-Display path

**Status:** design, awaiting operator direction-check (per
[`README.md`](./README.md) §"The per-element process", step 2).
**Kind:** `slider` — interactive value input, element #2 of the three
non-atomic mutable kinds (`input_text`, **`slider`**, `color_picker`).
**Exemplar:** the just-shipped `input_text` migration — its ABC element
([`input_text.py`](../../../src/punt_lux/protocol/elements/input_text.py)),
its OO codec
([`input_text_codec.py`](../../../src/punt_lux/protocol/elements/input_text_codec.py)),
its commit-on-idle arbiter
([`input_text_selection.py`](../../../src/punt_lux/display/renderers/imgui/input_text_selection.py)),
its renderer
([`input_text_renderer.py`](../../../src/punt_lux/display/renderers/input_text_renderer.py)),
and its ProB-verified reconciliation state machine
([`input_text_reconciliation.tex`](../../input_text_reconciliation.tex)).
**Tracking:** epic `lux-xs7r`; the shared-abstraction extraction deferred to
`color_picker` #3 is `lux-ld6y`.

---

## Top-line verdict: the input_text reconciliation model governs slider unchanged

**Yes.** The verified state machine in
[`input_text_reconciliation.tex`](../../input_text_reconciliation.tex) governs
`slider`'s drag reconciliation **unchanged** — same states, same operations,
same five invariants, same fidelity variants. Only the *type of the carried
value* differs: `slider` carries a `float` in `[min, max]` where `input_text`
carries a `str`. The model never reasons about anything string-specific. Its
basic type is an **abstract carrier** `[VALUE]` that ProB enumerates over a
bounded set; every operation reasons purely about value *equality* (`disp =
committed`, `hub = committed`) and value *movement* (the honour frames, the
echo, the agent push). Substituting "the set of reachable float positions in
`[min, max]`" for "the set of text values" changes nothing in the transition
relation or the invariants.

Therefore **this migration reuses
[`input_text_reconciliation.tex`](../../input_text_reconciliation.tex) as its
governing specification and adds no new Z spec.** The `.tex` is already
committed as a regression artifact; re-running `fuzz -t` plus the five
model-check goals whenever either arbiter changes covers slider too, because
the model is the shared discipline both elements implement.

The mapping from the model's vocabulary to slider's ImGui idiom:

| Model ([`.tex`](../../input_text_reconciliation.tex)) | `input_text` | `slider` |
| --- | --- | --- |
| `focused` | `is_item_active()` | `is_item_active()` (thumb grabbed / keyboard focus) |
| `edited` (real-edit witness) | `changed` from `input_text_with_hint` | `changed` from `slider_float` / `slider_int` |
| `Keystroke` (mid-edit change) | a typed character | a drag frame that moves the thumb |
| `Commit` (deactivate-after-edit) | blur / Enter | drag release (`is_item_deactivated_after_edit()`) |
| `HubEcho` | committed text returns as `elem.value` | committed float returns as `elem.value` |
| `AgentPush` | agent sets `value` while idle | agent sets `value` while idle |
| `disp` | the ImGui text buffer | the ImGui thumb position |

The single point that needs a specifically-float argument — is *value-equality
reconciliation* safe for floats? — is discharged in §4 below. The answer is
yes, and for a sharper reason than the string case: two distinct drag positions
are essentially never bit-identical, so the model's masking edge (F2) is *less*
reachable for a slider than for a text field, not more.

---

## 1. What crosses the boundary, what is authoritative, what is local

Restating the Hub/Display split for this kind in the designer's own words, per
the direction-check discipline:

- **Hub-authoritative:** the slider's `value` (a `float`), plus its static
  `label` / `min` / `max` / `format` / `integer` / `tooltip`. The Hub's copy
  wins every disagreement. A committed drag routes to the Hub as a
  `ValueChanged`; the Hub's built-in state-sync handler writes the authoritative
  `value` and re-pushes the whole scene.
- **Crosses IPC:** the serialized `SliderElement` (a pickled `_pickled` entry in
  the `SceneMessage`, like every ABC element — see
  [`tests/CLAUDE.md`](../../../tests/CLAUDE.md) §"Level 2"), and the
  `RemoteEventHandlerInvocation` a display-side drag release produces.
- **Display-local, never re-pushed:** the *live drag* — the buffer/editing slots
  and the commit-echo slots the arbiter keeps in `WidgetState`. These are the
  Display's per-frame reconciliation state. The Hub neither sees them nor
  overwrites them; a whole-tree resend must not clobber a drag in progress. This
  is the exact "ephemeral view state stays Display-local" rule the audit's
  Decision (c) settles for interactive inputs.
- **Never crosses:** ImGui calls. `slider_float` / `slider_int` run only on the
  Display.

The slider is a **non-atomic mutable** control: a single user gesture (a drag)
passes the value through many intermediate states before release. That is what
makes it need the *same class* of continuous-edit reconciliation `input_text`
got — a naive "honour `elem.value` every frame" clobbers the value under the
user's thumb the moment a Hub re-push lands mid-drag, and a naive "fire on every
`changed`" emits one `ValueChanged` per drag frame. Both are the exact defects
the commit-on-idle model was built to prevent, and they reproduce on a slider
identically.

---

## 2. ABC migration mechanics

Follow `input_text` exactly. The concrete surface, class by class.

### 2.1 `SliderElement` on the Element ABC

Replace the legacy frozen dataclass at
[`slider.py`](../../../src/punt_lux/protocol/elements/slider.py) with an
`Element` ABC subclass
([`element_abc.py:49`](../../../src/punt_lux/domain/element_abc.py)), mirroring
[`input_text.py`](../../../src/punt_lux/protocol/elements/input_text.py) and
`checkbox.py` (the interactive-leaf exemplar) line for line:

- Keyword-only `__new__` with the `RAISING_FACTORY` / `NO_EMIT` sentinels from
  [`abc_di_defaults`](../../../src/punt_lux/protocol/elements/abc_di_defaults.py)
  (`input_text.py:58`). `super().__new__(cls, renderer_factory=…, emit=…)`.
- `_kind: Literal["slider"]` set in `__new__` (`input_text.py:75`); `kind`
  property returns it.
- Typed fields — the operator's directive "typed float value/min/max + a display
  format":
  - `_value: float`, `_min: float`, `_max: float` — total floats, no Optional.
  - `_format: str` (default `"%.1f"`). A printf conversion string is genuinely
    free-form text, not an enumeration, so `str` is correct here — this is *not*
    a PY-TS-14 "str-with-a-comment" violation; there is no finite value list to
    turn into a `Literal`.
  - `_integer: bool` (default `False`) — the discriminator that selects the
    `slider_int` render variant. It stays a `bool`; it is a genuine two-state
    flag, not a deferred design decision. (An alternative — split `slider` into
    two `Literal` kinds — is rejected: the wire kind is one `"slider"`, and the
    int/float choice is a rendering variant, not a distinct element in the
    catalog.)
  - `_tooltip: str | None` (default `None`) — PY-TS-14 OK, absence is the
    documented "no tooltip" contract, exactly as on `input_text`/`checkbox`.
  - `_label: str` (default `""`).
- Read-only `@property` accessors for every field (PY-EN-2), plus
  `action -> Literal["changed"]` (`input_text.py:106`).
- `_set_<field>` setters for the patch path, using
  [`PatchField`](../../../src/punt_lux/protocol/elements/patch_field.py):
  `_set_value` / `_set_min` / `_set_max` via `.as_number` (returns `float`),
  `_set_format` / `_set_label` via `.as_str`, `_set_integer` via `.as_bool`,
  `_set_tooltip` via `.as_optional_str`. `ProgressElement._set_fraction`
  ([`progress.py:96`](../../../src/punt_lux/protocol/elements/progress.py)) is
  the numeric-setter exemplar — it coerces then range-checks and lets
  `Element.apply_patch` roll back on raise; `_set_value` should do the same
  against `[min, max]` (see §5).
- `_remote_dispatch_specs()` returning
  `(RemoteDispatchSpec(ValueChanged, self.action, "value_changed"),)` — verbatim
  from `input_text.py:133` / `checkbox.py:117`. This is the whole of the D21
  wiring: the inverted wrap seam
  ([`remote_dispatch_spec.py`](../../../src/punt_lux/domain/remote_dispatch_spec.py),
  Decision (e), already shipped) needs no `isinstance` branch added — the kind
  just declares its spec.
- `to_dict` / `from_dict` delegators to the codec (§2.2), keeping the structural
  `domain.element.Element` Protocol satisfied (`input_text.py:139`).
- `validate()` (§5) and `resolved_props()` (the Level-5 introspection surface,
  `input_text.py:163`) returning `value` / `min` / `max` / `format` / `integer`
  / `tooltip`.

### 2.2 A dedicated OO codec — `slider_codec.py`

A new module `slider_codec.py` holding `JsonSliderDecoder` +
`JsonSliderEncoder` as **classes with methods** — never module-level
`_slider_to_dict` / `_slider_from_dict` functions (PY-OO-5, PY-OO-7). This is
the pattern
[`input_text_codec.py`](../../../src/punt_lux/protocol/elements/input_text_codec.py)
establishes and the one the CLAUDE.md "protocol codec functions" debt note
demands new work follow:

- **`JsonSliderDecoder`** — constructed once per tier with that tier's
  `renderer_factory` + `emit` + `HandlerDecoder` (`input_text_codec.py:64`).
  Its `decode` validates the boundary through
  [`ElementWireContext.for_kind("slider")`](../../../src/punt_lux/protocol/elements/element_wire.py)
  (`require_str("id")`, `optional_number("value"/"min"/"max")`,
  `optional_str("format")`, `optional_bool("integer")`), constructs the element,
  **installs the built-in `_UpdateValueHandler`** (below) via
  `add_handler(ValueChanged, …)`, then installs any wire-declared `handlers`
  (`input_text_codec.py:96`).
- **`_UpdateValueHandler`** — the serializable built-in that mirrors the
  authoritative value on the Hub when `ValueChanged` fires:
  `self._elem.apply_patch({"value": event.value})`. Direct analog of
  `_UpdateTextHandler` (`input_text_codec.py:32`), with `__reduce__` /
  `__setstate__` so it crosses the wire and the Display can wrap it.
- **`JsonSliderEncoder`** — stateless (`__slots__ = ()`), emitting `kind` / `id`
  / `label` / `value` / `min` / `max` / `format`, and `integer` only when
  `True`, byte-for-byte matching the legacy `SliderElement.to_dict`
  ([`slider.py:32`](../../../src/punt_lux/protocol/elements/slider.py)) so the
  characterization corpus stays green.
- A `build_standalone_slider_handler_decoder` builder (mirroring
  [`standalone_input_text_handler`](../../../src/punt_lux/protocol/standalone_input_text_handler.py))
  so `SliderElement.from_dict` can decode a handler-less slider with a
  `RaisingPublishSink`, exactly as `input_text.py:151` does.

### 2.3 Fork wiring points

The forked ABC path is joined at the same six seams `input_text` was, each cited
at the line the `input_text` entry sits on today:

1. **`element_factory.py`** — the inbound dispatcher:
   - add `"slider"` to `_ABC_KINDS`
     ([`element_factory.py:70`](../../../src/punt_lux/protocol/element_factory.py));
   - add `SliderElement` to `_ABC_LEAF_TYPES` (`element_factory.py:76`);
   - add a `"slider": JsonSliderDecoder(…).decode` entry to the `_decoders` dict
     (`element_factory.py:148`), wiring
     `build_standalone_slider_handler_decoder(publish_sink)`;
   - add `SliderElement` to the legacy-guard `isinstance` union in
     `_decode_legacy` (`element_factory.py:288`) so a slider that reaches the
     codec path fails loud instead of routing wrong.
2. **`encoder_factory.py`** — add `(SliderElement, JsonSliderEncoder().encode)`
   to `_DISPATCH`
   ([`encoder_factory.py:41`](../../../src/punt_lux/protocol/encoder_factory.py)).
3. **`protocol/elements/__init__.py`** — add `SliderElement` to the ABC-encode
   `isinstance` union in `_element_to_dict`
   ([`__init__.py:184`](../../../src/punt_lux/protocol/elements/__init__.py)) so
   its per-kind encoder owns tooltip emission (the checkbox/input_text lesson in
   the audit §2a — an omission here double-appends or drops the tooltip).
   `SliderElement` is already in the `Element` union (`__init__.py:129`) and
   `__all__`; those stay.
4. **`container_abc_gate.py`** — add `"slider"` to `_MIGRATED_ABC_KINDS`
   ([`container_abc_gate.py:24`](../../../src/punt_lux/protocol/elements/container_abc_gate.py))
   so an all-ABC `group` / `collapsing_header` / `tab_bar` containing a slider
   forks onto the ABC path rather than the whole subtree falling legacy. Do this
   **only** as part of this migration — the module's own comment states a kind
   joins the set only once its ABC decoder is wired.
5. **`display/domain_pump.py`** — add `SliderElement` to `_ABC_TYPES`
   ([`domain_pump.py:35`](../../../src/punt_lux/display/domain_pump.py)) (and its
   import) so an anonymous-id slider raises rather than silently taking the
   `dataclasses.replace` id-synthesis path an ABC instance cannot survive.
6. **`display/renderers/imgui/factory.py`** — add
   `(SliderElement, ImGuiSliderRenderer)` to `_DISPATCH`
   ([`factory.py:55`](../../../src/punt_lux/display/renderers/imgui/factory.py)),
   with a new `imgui/slider.py` adapter (below).

### 2.4 Removal from the legacy registry

Delete the legacy path in the same PR (PY-RF-2 — wire forward, delete old in one
commit; no two live paths for one kind):

- Remove the `register("slider", SliderElement, …)` line from
  `InputsRegistry.apply`
  ([`inputs.py:44`](../../../src/punt_lux/protocol/elements/inputs.py)).
- Remove the `(SliderElement, "_slider_renderer")` dispatch entry and the
  `_slider_renderer` `WidgetState` re-thread entry from `ElementRenderer`
  ([`element_renderer.py:162`, `:176`](../../../src/punt_lux/display/element_renderer.py)),
  and drop the legacy `SliderRenderer` construction (`element_renderer.py:137`).
- The legacy fire-every-change renderer at
  [`slider_renderer.py`](../../../src/punt_lux/display/renderers/slider_renderer.py)
  is superseded (§3) — `mv` it out per the destructive-ops rule, verify, then
  delete.

### 2.5 The `ValueChanged` payload union — the one protocol touch

`ValueChanged.value` is typed `bool | str` today
([`interaction.py:78`](../../../src/punt_lux/domain/interaction.py)) — a checkbox
carries `bool`, an input_text edit carries `str`. A slider commit carries a
`float`, so the union must widen to `bool | int | float | str` (the `int` covers
the `slider_int` variant; `float` the default). Update the annotation on both
the field and the `__new__` parameter (`interaction.py:78`, `:87`), and refresh
the PY-TS-14 justification comment to name the three discriminating kinds. This
is a genuine (small) protocol change — flag it in the CHANGELOG and note that
`RemoteDispatchGroup`'s wire stamping already carries an opaque `value`, so no
transport code changes.

---

## 3. Drag reconciliation — a bespoke `SliderArbiter`

Per the **Rule of Three** (operator directive, binding): do **not** extract a
shared abstraction now. `slider` is element #2; the shared extraction waits for
`color_picker` #3 (`lux-ld6y`). Build a bespoke `SliderArbiter` in a new
`display/renderers/imgui/slider_selection.py`, structurally identical to
[`InputTextArbiter`](../../../src/punt_lux/display/renderers/imgui/input_text_selection.py)
wherever the logic is the same, so the eventual #3 extraction is mechanical.

### 3.1 The arbiter surface (identical shape to InputTextArbiter)

```python
class SliderArbiter:
    __new__(state: WidgetState, element_id: str)
    resolve(hub_value: float) -> float      # honour-or-defer, per frame
    observe(*, edited: bool, value: float) -> None   # defer only on real drag
    commit(value: float, hub_value: float) -> None   # open the optimistic-echo window
    release() -> None                        # go idle, drop buffer, keep commit record
    _editing (property) / _forget_commit()   # internal
```

The four `WidgetState` slots, the `observe` edit-gating, the `commit`
optimistic-echo record, the `release` semantics, and the `resolve` decision tree
are copied verbatim from `InputTextArbiter` — the whole point of the Rule-of-Three
structural-identity requirement.

### 3.2 What the two arbiters SHARE (mechanical for the #3 extraction)

Everything below is byte-for-byte the same logic; only the value type's spelling
differs. The #3 extraction collapses these into one generic
`ContinuousEditArbiter[T]` (or an arbiter parameterised by a value accessor):

| Shared element | InputText | Slider |
| --- | --- | --- |
| Four slots keyed off the element id | buffer / editing / committed / commit-hub | same |
| Slots survive a whole-UI re-push (commit may be in flight across the resend) | yes | yes |
| Slots cleared in `WidgetState.discard_for` on removal | yes | yes |
| `observe` defers **only** on `edited or already-editing` — never on mere focus/grab | yes | yes |
| `commit(v, hub)` records committed + commit-time hub; does **not** clear editing | yes | yes |
| `release` clears editing + drops buffer; keeps the commit record | yes | yes |
| `resolve`: editing → buffer; elif committed set and `hub == commit-hub` → committed; else forget + hub | yes | yes |
| Reconciliation is by **value equality alone** — no echo token, single-slot latest-commit | yes | yes |
| The two non-loss limits (F1 double-commit flicker, F2 agent-back-to-commit masking) | yes | yes (§6) |
| The five invariants of [`input_text_reconciliation.tex`](../../input_text_reconciliation.tex) | governed | governed |

### 3.3 What GENUINELY DIFFERS (enumerated, so #3 knows exactly what to parametrise)

1. **The carried value's type: `str` → `float`.** The buffer slot stores a
   `float`, not a `str`. `WidgetState.get_str`
   ([`widget_state.py:38`](../../../src/punt_lux/scene/widget_state.py)) is
   string-specific and returns `""` on miss; the slider path needs a numeric read
   — either a new `WidgetState.get_float(key, default)` or a direct
   `get(key, default=<min>)` with a float default. This is the **only** load-bearing
   type-touch. The #3 extraction parametrises exactly this accessor.
2. **No "empty value" state.** `input_text` distinguishes a *cleared* field
   (`""`, a real edited state) from an *idle* field (falls back to the Hub) —
   see `InputTextArbiter` tests `test_editing_keeps_a_cleared_field_empty`. A
   `float` slider has no empty analog; every value is a value. So the slider
   arbiter drops the empty-string discrimination — its "buffer" default is the
   current Hub value (or `min`), never a sentinel. Concretely, `observe`/`resolve`
   are simpler by exactly the amount `input_text` spends on `""`.
3. **The new-value source per frame.** `input_text` reads the widget's returned
   text buffer; `slider` reads `slider_float`'s / `slider_int`'s returned
   *clamped thumb position*. The value handed to `observe`/`commit` is that
   returned number, already in `[min, max]` (ImGui clamps).
4. **The int variant.** `slider_int` returns an `int`; the field stores
   `float(int)` (exact — see §4). The commit fires `ValueChanged` with the
   `int` (or `float`) value; the union in §2.5 admits both. This is a slider-only
   wrinkle with no `input_text` counterpart, but it does not touch the
   reconciliation logic — an `int` is just a float that happens to be integral.

**Net:** the arbiter differs in *one* place (the value accessor's type) plus the
*absence* of a special case (the empty-string branch). Nothing in the
honour/defer/commit/echo control flow differs. That is precisely the "structurally
identical" the directive asks for, and precisely why #3 is a mechanical
parametrisation and not a redesign.

### 3.4 The `WidgetState` slots — fork, don't share the constants (yet)

`WidgetState` today carries `INPUT_EDITING_SUFFIX` / `INPUT_COMMITTED_SUFFIX` /
`INPUT_COMMIT_HUB_SUFFIX`
([`widget_state.py:24`](../../../src/punt_lux/scene/widget_state.py)), cleared in
`discard_for` (`widget_state.py:70`). Per fork-don't-mix and Rule-of-Three,
**recommend** adding a parallel `SLIDER_EDITING_SUFFIX` /
`SLIDER_COMMITTED_SUFFIX` / `SLIDER_COMMIT_HUB_SUFFIX` triple and clearing them in
`discard_for` alongside the input triple, rather than reusing the `INPUT_*`
constants. Rationale: the two elements' Display-local state stays independent (a
slider and an input_text never share an id, but keeping the constants distinct
keeps the fork clean and makes the #3 extraction a rename of both triples into one
neutral `CONTINUOUS_EDIT_*` set). The alternative — reuse `INPUT_*` verbatim — is
zero new state but leaves a misleading `input_*` name on slider slots; it is a
judgment call for the implementer, noted here so it is a decision and not an
accident.

### 3.5 The renderer + adapter

- A new commit-on-idle `SliderRenderer` in `display/renderers/slider_renderer.py`
  (replacing the legacy one), shaped exactly like
  [`InputTextRenderer`](../../../src/punt_lux/display/renderers/input_text_renderer.py):
  build a fresh `SliderArbiter` per element per frame; call
  `slider_float(label, arbiter.resolve(elem.value), min, max, format)` (or
  `slider_int` when `elem.integer`); on `is_item_active()` call
  `observe(edited=changed, value=new_val)`, else `release()`; on
  `is_item_deactivated_after_edit()` `fire(ValueChanged(value=new_val))` **and**
  `commit(new_val, elem.value)`. The commit fire routes through the element's
  wrapped handler for D21 remote dispatch — the Display never runs the real
  handler locally.
- A new `imgui/slider.py` adapter `ImGuiSliderRenderer` mirroring
  [`ImGuiInputTextRenderer`](../../../src/punt_lux/display/renderers/imgui/input_text.py):
  a leaf that paints through `ElementRenderer`'s per-scene `slider_renderer` plus
  the shared `apply_tooltip` pass; `begin -> True`, `end` a no-op.

---

## 4. Float value-equality — the one thing to be rigorous about

The reconciliation compares `hub_value == commit-time-hub`
([`input_text_selection.py:75`](../../../src/punt_lux/display/renderers/imgui/input_text_selection.py)).
For `input_text` these are exact string copies; for a `float` slider the
question is whether exact `==` is safe. It is, for four reasons, each of which
must hold — and each does:

1. **Values are copied, never recomputed.** `commit(new_val, elem.value)` stores
   `elem.value` (the pre-echo Hub float) verbatim into the commit-hub slot.
   `resolve` compares the *current* `elem.value` against that stored copy. While
   the echo is in flight, `elem.value` has not changed, so the comparison is a
   float against a bit-identical copy of itself — exact equality holds trivially,
   independent of the float's precision. No arithmetic is applied on either side.
2. **The Hub round-trip does not reformat or quantize the float.** The commit
   value crosses to the Hub, whose `_UpdateValueHandler` does
   `apply_patch({"value": event.value})` → `PatchField.as_number` → `float(value)`.
   `float()` of an existing float is the identity. The value then re-serializes
   through JSON; CPython's `json` round-trips IEEE-754 doubles **exactly** (it has
   used repr-shortest round-tripping since 3.1), so the echoed `elem.value` equals
   the committed float bit-for-bit. The window therefore closes cleanly: when the
   echo lands, `hub` becomes the committed value, which differs from the pre-echo
   value (assuming the drag moved at all), so `resolve` forgets the record and
   honours the Hub — exactly the model's `HubEcho`.
3. **`format` is display-only and never quantizes the reconciled value.** The
   `"%.1f"` format controls the *label text* ImGui draws, not the value
   `slider_float` returns — the returned thumb position is full-precision. The
   value fired, committed, and reconciled is that returned float, so the format
   string cannot introduce a committed-vs-echoed mismatch. (The one place ImGui
   parses via the format is a Ctrl-click type-in; that produces a normal
   `changed` frame with a returned float, handled identically.)
4. **`min`/`max` clamping does not interact adversely with the honour path.**
   ImGui returns a value already clamped to `[min, max]`, so every value the
   arbiter ever stores is in range. The honour comparison is between two
   *already-clamped stored floats* (current hub vs commit-time hub); no re-clamp
   happens between commit and echo, and both tiers carry identical `min`/`max`,
   so there is no divergence. `_set_value`'s range check (§5) rejects an
   out-of-range **agent** push before it is installed, so an out-of-range value
   never reaches the reconciliation path to begin with.

**The degenerate case** — a drag that ends on the *exact* value it started from
(`committed == pre-echo`) — is the boundary `commit(x, hub_value=x)` the
`input_text` suite already proves durable
(`test_commit_value_equal_to_current_hub_persists_then_clears`,
`input_text_selection` §resolve): the record persists and is honoured while the
Hub reads `x`, and clears on the first Hub move to a different value. For a
slider this is a no-visible-change drag; it is safe, and no float subtlety
arises because `x == x` is exact.

**The float-specific *improvement* over the string case:** the model's F2
masking edge (an agent driving the Hub *back to the exact commit-time value*
during the window is indistinguishable from the pending echo) requires a
**bit-exact** float match for a slider. Two independent drag positions colliding
bit-for-bit is vanishingly less likely than two strings colliding, so F2 is
*less* reachable for slider than for input_text. The `int` variant is even
tighter — an agent override to a distinct integer is trivially distinguishable.

**Conclusion:** exact float `==` is the correct reconciliation predicate here.
No epsilon comparison, no rounding, no version token. Introducing an epsilon
would be a *bug*, not a safety measure — it would mask a genuine agent override
whose value happened to land within epsilon of the commit-time value. The model
governs unchanged.

---

## 5. Validation — `SliderElement.validate()` (DES-039)

Per [`element-contract.md`](../../target/element-contract.md) §"Validation
Contract" and the "validation rides with migration" rule, `slider` gains its
component-appropriate `validate()` as part of this migration.
`ProgressElement.validate()`
([`progress.py:123`](../../../src/punt_lux/protocol/elements/progress.py)) is the
numeric-leaf exemplar. The checks, each returning a `ValidationError(self._id,
self._kind, message)`:

1. **`min <= max`.** A range with `min > max` is degenerate; `slider_float` with
   an inverted range is undefined. Report it — this is the slider's headline
   invariant.
2. **`value` within `[min, max]`.** An out-of-range value paints a
   clamped-but-wrong thumb and, worse, seeds the reconciliation from a value the
   user can never reproduce by dragging. Report it. (Once `min <= max` is
   confirmed; if the range is already inverted, reporting the range error alone
   is enough — the implementer decides whether to also emit the bounds error or
   suppress it as noise. Recommend: emit both, so the agent sees every problem at
   once, per the no-fail-fast aggregation rule.)
3. **`value`, `min`, `max` all finite.** Reject `NaN` and `±inf`
   (`math.isnan` / `math.isinf`). A `NaN` value is doubly fatal here: it breaks
   ImGui's slider *and* the equality reconciliation (`NaN != NaN`), so a NaN
   committed value could never close its echo window. This check is stricter than
   `progress` needs and is the one genuinely slider-specific validation concern
   the float carrier introduces — call it out.
4. **`format` well-formed (recommended, implementer's call on strictness).** A
   `format` that is not a single printf float conversion (e.g. `"%d"` against a
   float, or a string with no conversion) can fault ImGui's C-side formatting. A
   minimal check — `format` is a non-empty `str` containing exactly one `%`
   conversion — closes a real crash class. Recommend including it; if the
   implementer judges the parse too fragile, at minimum validate `format` is a
   non-empty `str`. The wire decoder already rejects a non-`str` via
   `optional_str`, so this is a semantic check on top of the type check.
5. **`integer` consistency (optional).** When `integer=True`, `min`/`max`/`value`
   being non-integral is a mild data-shape smell (the int slider will truncate).
   This is a judgment call — recommend *not* reporting it (truncation is
   well-defined and harmless), noted so the implementer decides deliberately
   rather than by omission.

A single shared predicate (as `progress._fraction_out_of_range` does) should back
both `_set_value`'s write-path check and `validate()`, so the range invariant has
one source of truth.

---

## 6. Known edges — F1 and F2 apply identically

The two documented non-loss limits from
[`input_text_reconciliation.tex`](../../input_text_reconciliation.tex) §"Scope and
Known Limitations" apply to `slider` unchanged, and are deferred to the
echo-token scheme (`lux-ld6y`) exactly as for `input_text`:

- **F1 — two commits within one echo round-trip.** A slider dragged, released,
  grabbed, and released again *before the first echo returns* holds only the
  second commit in its single slot pair; the display can transiently revert to the
  intermediate authoritative Hub value — a one-frame flicker between the two
  committed positions — before the second commit's own echo lands. Transient
  display artifact, not data loss; both commits reach the Hub and both echoes
  land. Sub-millisecond on localhost.
- **F2 — agent drives the Hub back to the exact commit-time value.** Masked as the
  pending echo under value-equality reconciliation, until the field next moves off
  that value. As §4 notes, this is *less* reachable for a float slider than for a
  text field (bit-exact match required), so the limitation is even more benign
  here.

Both are transient, both need an event inside one echo round-trip, both are the
price of single-slot / value-equality simplicity, and both are the shared subject
of the future echo-token work — not slider-specific and not a blocker.

---

## 7. Test plan

Mirror the `input_text` test surface
([`tests/render/test_input_text_renderer.py`](../../../tests/render/test_input_text_renderer.py)),
which is the model of a fidelity-checked reconciliation suite. Every naive
implementation an invariant must beat is written out as a class the real arbiter
is diffed against.

### 7.1 Arbiter invariants (pure, imgui-free), each fidelity-checked

| Invariant | Assertion | Naive it beats |
| --- | --- | --- |
| **HONOUR-WHEN-IDLE** | an idle frame renders `elem.value`; a later agent drive appears next frame | seed-once arbiter (keeps the first value) |
| **DEFER-WHILE-DRAGGING / NO-CLOBBER** | while `is_item_active` and dragging, a Hub re-push does **not** overwrite the live thumb value | honour-every-frame arbiter (clobbers the drag) |
| **COMMIT-ON-RELEASE** | `is_item_deactivated_after_edit` fires exactly one `ValueChanged` with the final float; intermediate drag frames fire nothing | fire-per-changed-frame renderer (one event per drag frame) |
| **REFOCUS-DURABILITY** | through the echo window the field shows the committed float; a re-grab-without-drag shows it, and a further drag builds on committed, not pre-echo | defer-on-grab + raw-hub arbiter (loses the committed value) |
| **AGENT-OVERRIDE-MID-WINDOW** | an agent drive to a **distinct third** float mid-window drops the committed value and honours the Hub | an arbiter comparing `hub != committed` (keeps the stale committed value) |

The AGENT-OVERRIDE case must, as in
`test_agent_override_mid_window_drops_the_committed_value`, commit with a
*non-default* pre-echo value (e.g. `commit(v1, hub_value=old)` with `old != 0.0`)
and override to a *third* value, so a wrong `hub != committed` implementation is
actually caught. A degenerate `commit(x, hub_value=x)` boundary test proves the
record persists through equal-value frames and `_forget_commit` fires exactly on
the move (the `input_text` `test_commit_value_equal_to_current_hub_persists_then_clears`
analog).

Add a float-specific case the string suite cannot have: **exact-equality
reconciliation** — commit a full-precision drag float (e.g. `0.1 + 0.2`), echo
the *same* float, assert the window closes; then a bit-distinct neighbor, assert
it is honoured immediately. This is the executable form of §4.

### 7.2 Renderer paint-seam tests

Using the `_FakeImgui` pattern (a scripted `(changed, value)` per `slider_float`
call plus `is_item_active` / `is_item_deactivated_after_edit` flags), assert the
*value handed to the widget each frame* — the honour/defer evidence — for: idle
tracking, drag-does-not-clobber, grab-without-drag still honours, commit fires
once, no-fire-while-dragging, post-commit optimistic echo, agent-override, and
edit-in-window-wins-over-pending-commit. One removal-mid-drag test: `discard_for`
clears the slots and no `ValueChanged` fires (a removed slider does not commit).
Add an **int-variant** paint test: `slider_int` returns an int, the committed
`ValueChanged` carries the int, and `float(int)` reconciles exactly.

### 7.3 Level-4 real-socket scenario

Add one `Scenario.group_slider_progress()` value to `SCENARIOS`
([`tests/e2e/scenario.py:632`](../../../tests/e2e/scenario.py)) — a `group`
holding a publishing `slider` and a display-only `progress`, mirroring
`group_input_text_progress` (`scenario.py:192`):
`InteractionExpectation(event_kind="value_changed", value=<a float>)`, a wire
`handlers` entry publishing e.g. `level_changed`, and
`PropAfterDispatch(element_id="…", field="value", value=<float>, flipped=True)`.
Per the harness design, an interactive kind is **Level-4 green** when it has a
passing `Scenario`; this is **one more `Scenario` value, not new assertion code** —
the I1–I6 loop invariants run over it automatically across the real
`InMemoryConnection` boundary (the built-in state-sync handler writes the Hub
`value`, a real subscriber receives the business event, the agent reacts, and the
re-push reflects the mutated value).

### 7.4 Codec + crossing + introspection

- **Level 1** — build → `to_dict` → `from_dict` → equal, over the field matrix
  (float value, custom `min`/`max`, `format`, `integer=True`, tooltip present /
  absent).
- **Level 2** — the ABC wire form: a scene containing the slider serializes with
  the slider as a pickled `_pickled` entry in the `SceneMessage`, deserializes,
  and compares equal (the distinct surface the checkbox half-migration missed).
- **Level 3** — install into `HubDisplay`, push to the Display, assert an equal
  replica (real domain objects, no stub).
- **Level 5** — `inspect_scene` reports `render_path == "abc"` for the slider and
  `resolved_props` reads back `value` / `min` / `max` / `format` / `integer`
  including defaults.
- **Self-validation** — valid input renders; each malformed case (`min > max`,
  out-of-range `value`, `NaN`, bad `format`) is returned by `validate()` and the
  tree is **not** rendered (drive through `show()`, assert the client is never
  called), including one case **nested** in a `group` so the hierarchy walk is
  exercised.

### 7.5 z-spec regression re-run (no new spec)

Because the migration reuses
[`input_text_reconciliation.tex`](../../input_text_reconciliation.tex) as the
governing spec (§verdict), the merge gate for the reconciliation logic is
re-running that model against the shared discipline both arbiters now implement:
`fuzz -t docs/input_text_reconciliation.tex` clean, and the five ProB goals
(`lost`, `editing∧¬edited`, `clobbered`, `fires>1`, deadlock) all reporting the
verified verdict, at `DEFAULT_SETSIZE` 2 and 3. If — and only if — implementation
surfaces a genuinely different interleaving or invariant for slider (none is
anticipated; §4 is the rigorous negative), that is the recurrence signal to
*extend* the spec, not to patch empirically. The design's claim is that no such
delta exists: the model is type-agnostic and slider is a type substitution.

---

## 8. Summary of decisions for the direction-check

- **Reuse the verified `input_text` reconciliation model unchanged; add no new
  z-spec.** Slider is a value-type substitution (`str` → `float`) over a
  type-agnostic state machine.
- **Exact float `==` is the correct reconciliation predicate** — values are
  copied not recomputed, JSON round-trips doubles exactly, `format` is
  display-only, clamping is pre-applied. An epsilon would be a bug.
- **Bespoke `SliderArbiter`, structurally identical to `InputTextArbiter`**; the
  two share everything but the value accessor's type and the absence of the
  empty-value special case (§3.3). The #3 (`color_picker`, `lux-ld6y`) extraction
  is a mechanical parametrisation.
- **One protocol touch:** widen `ValueChanged.value` to admit `float`/`int`.
- **`validate()` checks `min <= max`, in-range `value`, finite floats, and
  (recommended) a well-formed `format`.**
- **F1/F2 apply identically and are deferred to `lux-ld6y`**, and F2 is *less*
  reachable for a float slider than for a text field.
