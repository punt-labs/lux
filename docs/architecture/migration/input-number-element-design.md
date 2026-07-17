# Element migration: `input_number` onto the Element-ABC / Hub-Display path

**Status:** design, awaiting operator direction-check (per
[`README.md`](./README.md) §"The per-element process", step 2).
**Kind:** `input_number` — interactive value input, the **4th** non-atomic
mutable kind after `input_text`, `slider`, `color_picker`.
**Exemplar:** the shipped `slider` migration — its ABC element
([`slider.py`](../../../src/punt_lux/protocol/elements/slider.py)), its OO codec
([`slider_codec.py`](../../../src/punt_lux/protocol/elements/slider_codec.py)),
its commit-on-idle renderer
([`slider_renderer.py`](../../../src/punt_lux/display/renderers/slider_renderer.py))
and adapter
([`imgui/slider.py`](../../../src/punt_lux/display/renderers/imgui/slider.py)).
The reconciliation itself is the **now-shipped shared abstraction**
([`continuous_edit_selection.py`](../../../src/punt_lux/display/renderers/imgui/continuous_edit_selection.py)
— `ContinuousEditArbiter[T]`,
[`continuous_edit_accessors.py`](../../../src/punt_lux/display/renderers/imgui/continuous_edit_accessors.py)
— `ValueAccessor[T]` + the three leaf accessors), extracted in PR #253. The
ProB-verified, data-independent reconciliation state machine is
[`commit_on_idle_reconciliation.tex`](../../commit_on_idle_reconciliation.tex).
**Tracking:** epic `lux-xs7r`; this element is `lux-xs7r.1`.

---

## Verdict (read this first)

`input_number` is a **clean mechanical replay of `slider` + arbiter-reuse.** The
hard part — the continuous-edit reconciliation — is already built and shipped;
`input_number` reuses `ContinuousEditArbiter[float]` and the existing
`FloatValueAccessor` **unchanged**. The `slider` migration is the template, and
`input_number` is closer to it than `color_picker` was.

- **Accessor decision — reuse `FloatValueAccessor`, add nothing.** `input_number`
  carries an `int`-or-`float` value with an `integer` variant, exactly like
  `slider._integer`. The reconciliation carrier is `float`; the `int` variant is
  a coercion at the widget seam (`int(resolved)` into `input_int`, and the
  payload carries the `int`), and `float(int)` round-trips exactly. There is no
  need for a `NumberValueAccessor` or `IntValueAccessor` — the `int` variant is
  expressible as a coercion, so the minimal correct accessor is the one that
  already ships. See [§1](#1-the-value-accessor--reuse-floatvalueaccessor).
- **Non-atomic — confirmed.** Typing a number passes through intermediate states
  (`"1"` → `"15"` → `"150"`); the widget is `is_item_active()` during the edit
  and commits on `is_item_deactivated_after_edit()`. The commit-on-idle rule
  applies exactly as it does to `slider` and `input_text`. See
  [§2](#2-the-widget-and-the-non-atomic-confirmation).
- **Protocol touch — count 1.** `ValueChanged.value` is already
  `bool | int | float | str` (widened for `slider`), so `input_number`'s numeric
  value needs **zero** union widening. The one protocol change is activating the
  wire-dead `tooltip`. See [§4](#4-protocol-touch--one-not-two).
- **Mechanical, with one live-verification item — not an escalation.** The single
  point that is not a byte-for-byte copy of `slider` is the **step-button
  (`input_int`/`input_float` stepper) compound-widget behavior**. The grounded
  expectation is that it works unchanged (ImGui's `EndGroup` propagates the
  `Deactivated`/`Edited` status flags from a compound widget's sub-controls, which
  is exactly why `input_int`-with-steppers reports `is_item_deactivated_after_edit`
  correctly), and the `color_picker` sub-control precedent already models "a run of
  sequential whole-value commits." This is a *verify-live-during-implementation*
  item, not a design decision the leader must escalate. See
  [§2.2](#22-the-step-buttons--a-compound-widget-verified-live-not-escalated).
- **One genuine difference from `slider` worth naming (not escalating):**
  `input_number`'s bounds and step are **genuinely optional** — `min` / `max` /
  `step` are `float | None` (`None` = unbounded / no stepper), where `slider`'s
  bounds are total. See [§3.1](#31-optional-bounds-and-step--the-one-real-difference-from-slider).

**Local commit hash:** recorded at the end of this document once committed.

---

## The Hub/Display split for this kind — in the designer's own words

Per the direction-check discipline ([`README.md`](./README.md) step 1), restating
what crosses, what is authoritative, what is local:

- **Hub-authoritative:** `input_number.value` (a number stored as `float`), plus
  its static `label` / `min` / `max` / `step` / `format` / `integer` / `tooltip`.
  The Hub's copy wins every disagreement. A committed edit routes to the Hub as a
  `ValueChanged`; the Hub's built-in `_UpdateValueHandler` writes the
  authoritative `value` via `apply_patch` and re-pushes the whole scene.
- **Crosses IPC:** the serialized `InputNumberElement` (a pickled `_pickled`
  entry in the `SceneMessage`, like every ABC element), and the
  `RemoteEventHandlerInvocation` a display-side commit produces.
- **Display-local, never re-pushed:** the *live edit* — the buffer slot and the
  commit-echo slots the `ContinuousEditArbiter` keeps in `WidgetState` under the
  shared `CONTINUOUS_EDIT_*` suffixes
  ([`widget_state.py:33`](../../../src/punt_lux/scene/widget_state.py)). A
  whole-tree resend must not clobber an edit in progress.
- **Never crosses:** ImGui calls. `input_int` / `input_float` run only on the
  Display.

`input_number` is a **non-atomic mutable** control: a single gesture — typing a
value, or holding a repeat-stepper — passes the value through many intermediate
states before commit. That is exactly what makes it need the same continuous-edit
reconciliation `slider` got. A naive "honour `elem.value` every frame" clobbers
the value under the user's cursor the moment a Hub re-push lands mid-edit; a
naive "fire on every `changed`" emits one `ValueChanged` per keystroke. Both are
the exact defects the commit-on-idle model prevents, and they reproduce on
`input_number` identically. The legacy renderer
([`input_number_renderer.py:43`](../../../src/punt_lux/display/renderers/input_number_renderer.py))
exhibits the second defect today — it fires on every `changed` frame.

---

## 1. The value accessor — reuse `FloatValueAccessor`

**Decision: reuse the shipped `FloatValueAccessor`
([`continuous_edit_accessors.py:38`](../../../src/punt_lux/display/renderers/imgui/continuous_edit_accessors.py)).
No new accessor.**

The `ValueAccessor[T]` Protocol has exactly two carrier-typed touches
([`continuous_edit_selection.py:41`](../../../src/punt_lux/display/renderers/imgui/continuous_edit_selection.py)):
`read(state, key, hub_value)` (the buffer read + miss policy) and
`coerce(stored)` (the committed-value cast). `slider` passes `FloatValueAccessor`:
`read` returns `get_float(key, default=hub_value)` — a miss falls back to the
current Hub value, no empty sentinel — and `coerce` returns `float(stored)`.
`input_number`'s reconciliation carrier is a `float` in every respect `slider`'s
is:

1. **The carrier is `float`; the `int` variant is a coercion at the widget
   seam.** When `integer=True` the renderer calls `input_int(int(resolved), …)`
   and fires `ValueChanged(value=<int>)`; the buffer, the committed slot, and the
   commit-hub slot all hold `float`. This mirrors `slider`
   ([`slider_renderer.py:82`](../../../src/punt_lux/display/renderers/slider_renderer.py)):
   the reconciliation runs on `float`, `int↔float` conversion happens only at
   `input_int` / in the payload. `float(int)` is exact for any integer within
   2⁵³ (far beyond any UI value), so the `int` variant round-trips exactly.
2. **The commit-echo window closes exactly, for both variants.** `commit(v, hub)`
   stores `elem.value` (the pre-echo Hub `float`) verbatim; `resolve` compares the
   *current* `elem.value` against that copy by `==`
   ([`continuous_edit_selection.py:117`](../../../src/punt_lux/display/renderers/imgui/continuous_edit_selection.py)).
   The Hub round-trip is `float(value)` → JSON → `float`, and CPython's `json`
   round-trips IEEE-754 doubles bit-for-bit, so the echoed `elem.value` equals the
   committed `float` exactly. For the `int` variant the committed value is
   `float(new_int)`, an exactly-representable integer; its echo equals it
   trivially. This is the same argument `slider`'s design §4 makes; the `int`
   variant is *tighter*, not looser (an agent override to a distinct integer is
   trivially distinguishable).
3. **No empty-value state.** `input_text` distinguishes a cleared field (`""`, a
   real edited state) from an idle field; a numeric input has no empty analog —
   every value is a value. So `input_number` uses `FloatValueAccessor`'s
   Hub-fallback miss policy, exactly as `slider` does. The empty-string asymmetry
   lives only in `StrValueAccessor` and never touches this migration.

**Rejected alternative — a dedicated `IntValueAccessor`.** One could imagine a
separate integer carrier so the `int` variant never becomes a `float` internally.
It is rejected: it would fork the arbiter's type surface for a variant that is
already exactly expressible as a `float` coercion (`slider` proves this in
production), it would double the accessor count for no soundness gain, and it
would break the "one accessor per element" shape the shared extraction is built
around. The `int` variant is a *rendering* variant, not a distinct carrier.

---

## 2. The widget and the non-atomic confirmation

### 2.1 The typing path — identical to `slider`/`input_text`

`input_number` renders through `input_int` (integer variant) or `input_float`
(float variant). Typing is non-atomic: the field is `is_item_active()` while the
user edits, `changed` fires per keystroke, and `is_item_deactivated_after_edit()`
fires on blur / Enter. The renderer therefore follows the shipped pattern
verbatim
([`slider_renderer.py:62`](../../../src/punt_lux/display/renderers/slider_renderer.py),
[`input_text_renderer.py:57`](../../../src/punt_lux/display/renderers/input_text_renderer.py)):

- build a fresh `ContinuousEditArbiter(widget_state, elem.id, _ACCESSOR)` per
  frame (the `FloatValueAccessor` is stateless, one shared instance);
- draw with `arbiter.resolve(elem.value)` as the seeded value;
- on `is_item_active()`, `arbiter.observe(edited=changed, value=float(new_val))`;
  else `arbiter.release()`;
- on `is_item_deactivated_after_edit()`, `elem.fire(ValueChanged(value=new_val))`
  **and** `arbiter.commit(float(new_val), elem.value)`.

The commit fire routes through the element's wrapped handler for D21 remote
dispatch — the Display never runs the real handler locally. This is the whole of
the reconciliation wiring, and it is a copy of `slider`'s.

### 2.2 The step buttons — a compound widget, verified live, not escalated

`input_int` / `input_float` with `step > 0` render `+`/`−` repeat steppers around
the numeric field. This is the one behavior that is *not* a byte-for-byte copy of
`slider` (`slider_float`/`slider_int` is a single widget), so it is called out
explicitly.

**Expected behavior (grounded, high confidence).** ImGui composes the stepper
form of `InputScalar` inside a `BeginGroup()`/`EndGroup()` pair, and `EndGroup()`
propagates the `Deactivated` and `Edited` status flags from the group's
sub-controls up to the group's "last item." That propagation is precisely why
`input_int`-with-steppers reports `is_item_deactivated_after_edit()` correctly at
all — the pattern the wider ImGui ecosystem relies on to commit-on-idle these
widgets. Under that behavior:

- typing then blurring fires one `is_item_deactivated_after_edit` → one commit;
- each stepper click is a discrete whole-value change: the group is active while
  the button is held (repeat), `observe` buffers the incremented value, and the
  release fires `is_item_deactivated_after_edit` → one commit.

A gesture across the field and the steppers is therefore a **run of sequential
whole-value commits** — the single-slot commit-on-idle case — exactly the shape
`color_picker`'s sub-controls take (its peer-review amendment #1: "sub-control
commits are sequential whole-color commits, not partials"). The arbiter handles
them with no new behavior: each commit overwrites the single committed/commit-hub
slot pair, and its echo closes its own window.

**The verify-live item.** Because this is compound-widget behavior in the
specific `imgui-bundle` build, implementation must confirm it live (per the
Definition of Done, item 6): drive a stepper click through the real widget and
assert via introspection that exactly one `ValueChanged` fired and the Hub value
advanced by one step — not zero (a swallowed commit) and not many (a per-frame
fire). Write the expected output first, then compare.

**Fallback if the expectation does not hold.** If, in this ImGui build, a stepper
click returns `changed=True` but never fires `is_item_deactivated_after_edit`
(i.e. the group does not propagate the flag), the minimal correct fix is a
discrete-change commit: when `changed and not is_item_active()`, treat the frame
as a discrete commit (`fire` + `commit`) — the non-typing analog of the deactivate
path. This keeps the arbiter untouched; it only adds a second commit trigger in
the renderer. It is documented here so the implementer has a decided answer rather
than a mid-flight surprise. The recommendation is to keep the steppers and verify;
the conservative alternative — omit steppers in the ABC form (a pure numeric text
field, `step` becoming a no-op, a behavior removal) — is available but **not
recommended**, since it drops a legacy capability to sidestep a verification the
`color_picker` precedent says is unnecessary.

---

## 3. ABC migration mechanics — follow `slider`

`input_number` is numeric with patchable bounds, so it mirrors `slider`
class-for-class (not `color_picker`, which had no numeric cross-field invariant).
The concrete surface:

### 3.1 Optional bounds and step — the one real difference from `slider`

`slider`'s `min`/`max` are total `float`s (a slider always has a range).
`input_number`'s bounds and step are **genuinely optional**:

- `_min: float | None` (default `None`) — `None` = no lower bound (unclamped).
- `_max: float | None` (default `None`) — `None` = no upper bound.
- `_step: float | None` (default `None`) — `None` = no stepper buttons.

Per PY-TS-14 (reduce `| None`, justify what remains), each of these is a
**documented discriminated state**, not a sentinel-default the type system gave
up on: "unbounded" and "no stepper" are real, distinct semantics with no natural
`float` value to stand in for them (using `±inf` for "unbounded" would fight the
finiteness precondition machinery of §3.5). They therefore stay `| None` with an
inline justification comment. This is the honest model and the one field-shape
difference from `slider` worth naming. `_value` stays a total `float`; `_format`,
`_integer`, `_label` mirror `slider`; `_tooltip: str | None` (PY-TS-14 OK,
absence = no tooltip).

### 3.2 `InputNumberElement` on the Element ABC

Replace the legacy frozen dataclass at
[`input_number.py`](../../../src/punt_lux/protocol/elements/input_number.py) with
an `Element` ABC subclass, `@final`, mirroring
[`slider.py`](../../../src/punt_lux/protocol/elements/slider.py) (PY-CC-1
`__new__`, PY-IC-2 `@final`):

- Keyword-only `__new__` with the `RAISING_FACTORY` / `NO_EMIT` sentinels from
  [`abc_di_defaults`](../../../src/punt_lux/protocol/elements/abc_di_defaults.py);
  `super().__new__(cls, renderer_factory=…, emit=…)`.
- `_kind: Literal["input_number"]` set in `__new__`; `kind` property returns it.
- Typed fields per §3.1. Variant-derived default format via a module constant
  `_DEFAULT_FORMATS: dict[bool, str] = {False: "%.3f", True: "%d"}` — note the
  float default is `%.3f`, matching the legacy dataclass, **not** `slider`'s
  `%.1f`. The `format` *parameter* is `str | None` (`None` → variant default);
  the stored `_format` is always a concrete `str`.
- Read-only `@property` accessors for every field (PY-EN-2), plus
  `action -> Literal["changed"]`.
- `_set_<field>` setters using
  [`PatchField`](../../../src/punt_lux/protocol/elements/patch_field.py):
  `_set_value` via `.as_number`; `_set_min` / `_set_max` / `_set_step` via a
  **new** `PatchField.as_optional_number` (returns `float | None` — the small
  helper this migration adds, §3.6); `_set_format` / `_set_label` via `.as_str`;
  `_set_integer` via `.as_bool`; `_set_tooltip` via `.as_optional_str`. The
  numeric setters only coerce — the range/finiteness invariant is re-checked once
  for the whole element at the boundary, never per setter (§3.3).
- `apply_patch` override, verbatim in shape from
  [`slider.py:164`](../../../src/punt_lux/protocol/elements/slider.py): snapshot
  `vars(self)`, run the base setter loop, re-check `_range_error_messages()`, roll
  the element back whole on failure. This is why a combined
  `{"value": 150, "max": 200}` applied value-first against a stale `max` is judged
  on its final state and accepted (§3.3).
- `_remote_dispatch_specs()` returning
  `(RemoteDispatchSpec(ValueChanged, self.action, "value_changed"),)` — the whole
  of the D21 wiring; the inverted wrap seam needs no `isinstance` branch.
- `to_dict` / `from_dict` delegators to the codec (§3.4), keeping the structural
  `domain.element.Element` Protocol satisfied.
- `validate()` (§3.5), `widget_value()` returning `self._value`, and
  `resolved_props()` returning `value` / `min` / `max` / `step` / `format` /
  `integer` / `tooltip`.

### 3.3 The range/finiteness predicate — shared, boundary-checked (from `slider`)

Because `min`/`max`/`value` are all patchable, the invariant is re-checked for the
whole element at the boundary — not per setter — via a single
`_range_error_messages()` predicate that backs both `validate()` and the
`apply_patch` re-check, exactly as `slider`
([`slider.py:190`](../../../src/punt_lux/protocol/elements/slider.py)). The
predicate differs from `slider`'s only in skipping a bound comparison when that
bound is `None` (optional bounds, §3.1): a missing lower bound imposes no lower
constraint; a missing upper bound none upper.

### 3.4 A dedicated OO codec — `input_number_codec.py`

A new module `input_number_codec.py` holding `JsonInputNumberDecoder` +
`JsonInputNumberEncoder` as **classes with methods** — never module-level
`_input_number_to_dict` / `_from_dict` functions (PY-OO-5, PY-OO-7), the pattern
[`slider_codec.py`](../../../src/punt_lux/protocol/elements/slider_codec.py)
establishes and the CLAUDE.md "protocol codec functions" debt note demands. The
legacy `InputNumberElement.to_dict`/`.from_dict`
([`input_number.py:36`](../../../src/punt_lux/protocol/elements/input_number.py))
are the procedural pattern being retired.

- **`JsonInputNumberDecoder`** — constructed once per tier with that tier's
  `renderer_factory` + `emit` + `HandlerDecoder`. Its `decode` validates the
  boundary through `ElementWireContext.for_kind("input_number")`:
  `require_str("id")`, `optional_number("value")`,
  `optional_nullable_number("min"/"max"/"step")` (the helper the legacy
  `from_dict` already uses — [`element_wire.py:124`](../../../src/punt_lux/protocol/elements/element_wire.py)),
  `optional_nullable_str("format")`, `optional_bool("integer")`,
  `optional_nullable_str("tooltip")`; constructs the element; **installs the
  built-in `_UpdateValueHandler`** via `add_handler(ValueChanged, …)`; then
  installs any wire-declared `handlers`. `_UpdateValueHandler` is the direct
  analog of `slider`'s (`self._elem.apply_patch({"value": event.value})`, with
  `__reduce__` / `__setstate__` so it crosses the wire).
- **`JsonInputNumberEncoder`** — stateless (`__slots__ = ()`), emitting `kind` /
  `id` / `label` / `value` / `format`, and `min` / `max` / `step` only when
  present, `integer` only when `True`, `tooltip` only when present. This matches
  the legacy `to_dict` byte-for-byte in the tooltip-absent case; a present tooltip
  is new wire (§4).
- A `build_standalone_input_number_handler_decoder` builder (mirroring
  [`build_standalone_slider_handler_decoder`](../../../src/punt_lux/protocol/standalone_slider_handler.py))
  so `InputNumberElement.from_dict` decodes a handler-less input with a
  `RaisingPublishSink`.

### 3.5 Validation — `InputNumberElement.validate()` (DES-039)

Per [`element-contract.md`](../../target/element-contract.md) §"Validation
Contract" and the "validation rides with migration" rule, `input_number` gains
its `validate()` as part of this migration. `slider.validate()`
([`slider.py:249`](../../../src/punt_lux/protocol/elements/slider.py)) is the
exemplar; the checks, aggregated (no fail-fast), each a
`ValidationError(self._id, self._kind, message)`:

1. **`value` finite; `min`/`max`/`step` finite when present.** `math.isfinite`.
   This is the **soundness precondition** for the value-equality reconciliation
   (§6), not a mere nicety — `NaN` is the one float where `x == x` is false, so a
   committed `NaN` could never close its echo window. Raw numbers cross the wire
   here (unlike `color_picker`'s hex), so the guard is active, as on `slider`.
   Non-finite reports alone (integrality/bounds against `NaN` is noise).
2. **`min <= max` when both present.** An inverted explicit range is degenerate.
   Reported alone when it fires.
3. **`value` within `[min, max]`** for whichever bounds are present. An
   out-of-range value seeds the reconciliation from a value the user can never
   reproduce by typing within bounds.
4. **integer variant → integral `value`, and integral `min`/`max`/`step` when
   present.** `input_int` truncates, so a non-integral bound would let a truncated
   commit fall outside the range the Hub re-checks — the same lesson `slider`'s
   review rounds settled
   ([`slider.py:206`](../../../src/punt_lux/protocol/elements/slider.py)).
5. **`step >= 0` when present.** A negative step is a degenerate stepper; `0` is
   the documented "no buttons" value.
6. **`format` well-formed** — a single variant-matching printf conversion
   (`diouxX` for the integer variant, `eEfFgGaA` for float), the same check
   `slider` applies ([`slider.py:236`](../../../src/punt_lux/protocol/elements/slider.py)).
   (`input_int` ignores `format`, but validating it keeps parity and catches a
   malformed float `format`.)

### 3.6 Small shared helper added: `PatchField.as_optional_number`

`PatchField` today has `as_number` (→ `float`) but no optional variant
([`patch_field.py:51`](../../../src/punt_lux/protocol/elements/patch_field.py)).
`input_number`'s `_set_min`/`_set_max`/`_set_step` need `float | None` coercion
(a `None` patch clears the bound/stepper). Add `as_optional_number(value) ->
float | None`: `None` passes through; a number coerces to `float`; anything else
raises `TypeError` (PY-EH-2), mirroring `as_optional_str`. This is a one-method
addition to an existing class, on the class that owns the vocabulary (PY-OO-7).

---

## 4. Protocol touch — one, not two

`slider` made two protocol changes: a `ValueChanged.value` union widening and a
tooltip activation. `input_number` makes **only the tooltip one** — the union is
already wide enough.

- **(No union widening.)** `ValueChanged.value` is `bool | int | float | str`
  today ([`interaction.py:78`](../../../src/punt_lux/domain/interaction.py)),
  widened for `slider`. `input_number` commits an `int` (integer variant) or a
  `float`, both already covered. **Zero** annotation change. Refresh only the
  PY-TS-14 justification comment to name `input_number` alongside `slider` as a
  `float`/`int` producer.
- **Tooltip activation.** `tooltip` is wire-**dead** on the legacy
  `input_number`: the dataclass carries a `tooltip: str | None` field, but
  `to_dict` never emits it and `from_dict` never reads it
  ([`input_number.py:36`](../../../src/punt_lux/protocol/elements/input_number.py)).
  This migration **activates** it — the encoder emits `tooltip` when present, the
  decoder reads it — for parity with `slider` / `input_text` / `checkbox` /
  `color_picker`. The encoder is byte-identical to the legacy `to_dict` only in
  the tooltip-absent case; a present tooltip is new wire. Flag it in the
  CHANGELOG.

---

## 5. The six fork-wiring seams, and legacy removal

The forked ABC path joins at the same six seams `slider` and `color_picker`
joined, each cited at the line the existing ABC-kind entries sit on today.

1. **`element_factory.py`** — the inbound dispatcher
   ([`element_factory.py`](../../../src/punt_lux/protocol/element_factory.py)):
   - add `"input_number"` to `_ABC_KINDS` (`element_factory.py:80`);
   - add `InputNumberElement` to `_ABC_LEAF_TYPES` (`element_factory.py:95`);
   - add an `"input_number": JsonInputNumberDecoder(…).decode` entry to the
     `_decoders` dict (`element_factory.py:142`), wiring
     `build_standalone_input_number_handler_decoder(publish_sink)`;
   - add `InputNumberElement` to the legacy-guard `isinstance` union in
     `_decode_legacy` (`element_factory.py:319`) so an input_number reaching the
     codec path fails loud instead of routing wrong.
2. **`encoder_factory.py`** — add
   `(InputNumberElement, JsonInputNumberEncoder().encode)` to `_DISPATCH`
   ([`encoder_factory.py:45`](../../../src/punt_lux/protocol/encoder_factory.py)).
3. **`protocol/elements/__init__.py`** — add `InputNumberElement` to the
   ABC-encode `isinstance` union in `_element_to_dict`
   ([`__init__.py:179`](../../../src/punt_lux/protocol/elements/__init__.py)) so
   its per-kind encoder owns tooltip emission (the checkbox/input_text lesson: an
   omission here double-appends or drops the tooltip). `InputNumberElement` is
   already in the `Element` union (`__init__.py:133`) and `__all__`; those stay.
4. **`container_abc_gate.py`** — add `"input_number"` to `_MIGRATED_ABC_KINDS`
   ([`container_abc_gate.py:24`](../../../src/punt_lux/protocol/elements/container_abc_gate.py))
   so an all-ABC `group` / `collapsing_header` / `tab_bar` containing an
   input_number forks onto the ABC path rather than the whole subtree falling
   legacy. Do this **only** as part of this migration — the module's comment
   states a kind joins the set only once its ABC decoder is wired.
5. **`display/domain_pump.py`** — add `InputNumberElement` to `_ABC_TYPES`
   ([`domain_pump.py:37`](../../../src/punt_lux/display/domain_pump.py)) (and its
   import) so an anonymous-id input_number raises rather than silently taking the
   `dataclasses.replace` id-synthesis path an ABC instance cannot survive. Refresh
   the stale docstring naming the "nine inputs" (`domain_pump.py:54`) while there.
6. **`display/renderers/imgui/factory.py`** — add
   `(InputNumberElement, ImGuiInputNumberRenderer)` to `_DISPATCH`
   ([`factory.py:59`](../../../src/punt_lux/display/renderers/imgui/factory.py))
   with the new `imgui/input_number.py` adapter (§5.2), and its import.

### 5.1 Removal from the legacy registry

Delete the legacy path in the same PR (PY-RF-2 — wire forward, delete old in one
commit; no two live paths for one kind):

- Remove the `register("input_number", InputNumberElement, …)` block from
  `InputsRegistry.apply`
  ([`inputs.py:42`](../../../src/punt_lux/protocol/elements/inputs.py)) and its
  import.

### 5.2 The renderer + adapter — swap in place, mirror `slider`

Following the `color_picker` A.4 correction (mirror `slider` exactly), the native
renderer **stays** in `ElementRenderer`, swapped from fire-every-change to
commit-on-idle:

- Replace the legacy `InputNumberRenderer`
  ([`input_number_renderer.py`](../../../src/punt_lux/display/renderers/input_number_renderer.py))
  body with a commit-on-idle renderer shaped exactly like `SliderRenderer`
  ([`slider_renderer.py`](../../../src/punt_lux/display/renderers/slider_renderer.py)):
  construct with **`widget_state` only** (drop `emit_event` — the D21 fire replaces
  it); build a fresh `ContinuousEditArbiter(widget_state, elem.id,
  FloatValueAccessor())` per frame; draw the `input_int`/`input_float` variant;
  `observe` while active / `release` otherwise; `fire(ValueChanged)` + `commit` on
  deactivate-after-edit (plus the discrete-stepper trigger of §2.2 if the
  live-verification requires it). `mv` the legacy body out per the destructive-ops
  rule, verify, then delete.
- In `ElementRenderer`
  ([`element_renderer.py`](../../../src/punt_lux/display/element_renderer.py)):
  keep the `_input_number_renderer` field, its `_NATIVE_DISPATCH` entry
  (`element_renderer.py:166`), and its `_WIDGET_STATE_RENDERERS` entry
  (`element_renderer.py:179`); change its construction (`element_renderer.py:141`)
  from `InputNumberRenderer(widget_state, emit_event)` to
  `InputNumberRenderer(widget_state)`; add an `input_number_renderer` property (the
  seam the ImGui adapter paints through), mirroring `slider_renderer`
  (`element_renderer.py:222`) and `color_picker_renderer` (`element_renderer.py:232`).
- A new `imgui/input_number.py` adapter `ImGuiInputNumberRenderer` mirroring
  [`imgui/slider.py`](../../../src/punt_lux/display/renderers/imgui/slider.py): a
  leaf that paints through `ElementRenderer`'s per-scene `input_number_renderer`
  plus the shared `apply_tooltip` pass; `begin -> True`, `end` a no-op.

---

## 6. z-spec — reuse `commit_on_idle_reconciliation.tex` unchanged, no new spec

The shipped `ContinuousEditArbiter[T]` is the governed reconciliation, and its
governing spec is the data-independent
[`commit_on_idle_reconciliation.tex`](../../commit_on_idle_reconciliation.tex), whose
carrier is the abstract `[VALUE]`. `input_number`'s carrier is `float` (with the
`int` variant a `float`-representable value) — a valid `[VALUE]` instantiation,
exactly as `str` (input_text), `float` (slider), and the RGBA tuple (color_picker)
are. The model reasons only about value *equality* and value *movement*; nothing
in its transition relation or its five invariants mentions the carrier's internal
structure. `int` and `float` are both valid `[VALUE]` values.

The one type-specific proof obligation — reflexivity of `==` under the honour
predicate — is the finiteness precondition, discharged at runtime by
`validate()`'s `math.isfinite` guard (§3.5), exactly as `slider` discharges it
(raw numbers cross the wire, so the guard is active rather than structural). For
the `int` variant, integrality is exact and reflexivity is trivial.

Therefore this migration **adds no new Z spec.** The merge gate for the
reconciliation logic is re-running the shared model: `fuzz -t
docs/commit_on_idle_reconciliation.tex` clean, and the five ProB goals (`lost`,
`editing∧¬edited`, `clobbered`, `fires>1`, deadlock) at `DEFAULT_SETSIZE` 2 and 3
reporting the verified verdict — since the model is the shared discipline all four
arbiters now implement. The two documented non-loss limits (F1 double-commit
flicker, F2 same-value masking) apply identically and are deferred to the
echo-token scheme with the other three kinds; F2 is *less* reachable for a numeric
input than for text (bit-exact float match required).

---

## 7. Test plan — mirror the `slider` surface

Mirror the `slider` test surface (the fidelity-checked reconciliation suite),
substituting the numeric carrier and adding the `input_number`-specific cases.

- **Arbiter behavior** is already covered by the shared
  `ContinuousEditArbiter` tests (PR #253) over `FloatValueAccessor`; this
  migration adds **renderer paint-seam** tests over a scripted `_FakeImgui`:
  idle tracking, edit-does-not-clobber, grab-without-edit still honours, commit
  fires once, no-fire-while-editing, post-commit optimistic echo, agent-override,
  edit-in-window-wins-over-pending-commit, and removal-mid-edit
  (`discard_for` clears the slots, no `ValueChanged` fires). Add an **int-variant**
  paint test (`input_int` returns an `int`, the committed `ValueChanged` carries
  the `int`, `float(int)` reconciles exactly) and a **stepper** test asserting one
  commit per stepper click (the §2.2 live-verification item, encoded as a unit
  test against the scripted flags).
- **Codec + crossing (Levels 1–3, 5)** as `slider`: build → `to_dict` →
  `from_dict` → equal over the field matrix (float value, present/absent
  `min`/`max`/`step`, `format`, `integer=True`, tooltip present/absent); the ABC
  `_pickled` wire form in a `SceneMessage`; install into `HubDisplay` and assert an
  equal replica; `inspect_scene` reports `render_path == "abc"` and `resolved_props`
  reads back every field including defaults.
- **Self-validation** — each malformed case (`min > max`, out-of-range `value`,
  `NaN`, negative `step`, non-integral bound under `integer`, bad `format`) is
  returned by `validate()` and the tree is **not** rendered (drive through
  `show()`, assert the client is never called), including one case **nested** in a
  `group` so the hierarchy walk is exercised.
- **Level-4 real-socket scenario** — one `Scenario` value mirroring
  `group_input_text_progress` /
  the slider scenario: a `group` holding a publishing `input_number` and a
  display-only `progress`, with an `InteractionExpectation(event_kind="value_changed",
  value=<a number>)`, a wire `handlers` entry publishing a topic, and a
  `PropAfterDispatch(field="value", …)`. One more `Scenario` value, not new
  assertion code.

---

## 8. Write-set for the implementation mission

**Create:**

- `src/punt_lux/protocol/elements/input_number_codec.py` —
  `JsonInputNumberDecoder` + `JsonInputNumberEncoder` + `_UpdateValueHandler`.
- `src/punt_lux/protocol/standalone_input_number_handler.py` —
  `build_standalone_input_number_handler_decoder`.
- `src/punt_lux/display/renderers/imgui/input_number.py` —
  `ImGuiInputNumberRenderer` adapter.
- `tests/render/test_input_number_renderer.py` (or extend the existing test
  module) — the paint-seam + int-variant + stepper suite.
- Level-1/2/3/5 codec + crossing tests and the validation tests (mirroring the
  `slider` test files), and the one Level-4 `Scenario` value.

**Modify:**

- `src/punt_lux/protocol/elements/input_number.py` — replace the dataclass with
  the `@final` ABC subclass (fields per §3.1, setters, `apply_patch` override,
  `_range_error_messages`, `validate`, codec delegators, `resolved_props`).
- `src/punt_lux/protocol/elements/patch_field.py` — add `as_optional_number`.
- `src/punt_lux/protocol/element_factory.py` — seams 1 (four edits).
- `src/punt_lux/protocol/encoder_factory.py` — seam 2.
- `src/punt_lux/protocol/elements/__init__.py` — seam 3 (encode union).
- `src/punt_lux/protocol/elements/container_abc_gate.py` — seam 4.
- `src/punt_lux/display/domain_pump.py` — seam 5 (+ import, docstring).
- `src/punt_lux/display/renderers/imgui/factory.py` — seam 6 (+ import).
- `src/punt_lux/protocol/elements/inputs.py` — remove the legacy registration
  (+ import).
- `src/punt_lux/display/renderers/input_number_renderer.py` — swap to
  commit-on-idle (`widget_state`-only, `ContinuousEditArbiter`).
- `src/punt_lux/display/element_renderer.py` — change the `InputNumberRenderer`
  construction; add the `input_number_renderer` property.
- `docs/architecture/element-migration-audit.md` — refresh the per-element table
  and §2a (done in this branch; see below).
- `CHANGELOG.md` — the tooltip activation under `## [Unreleased]`.

**Delete (after wire-forward):**

- The legacy `InputNumberElement.to_dict`/`from_dict`/`widget_value` (absorbed
  into the codec and the ABC element); the legacy fire-every-change renderer body.

## 9. OO rules the implementation must follow

- **PY-OO-5 / PY-OO-7** — the codec is classes-with-methods
  (`JsonInputNumberDecoder`/`Encoder`), never module-level `_to_dict`/`_from_dict`;
  `as_optional_number` lands on `PatchField`, the class that owns the vocabulary.
- **PY-CC-1** — `__new__`, not `__init__`, on every new class.
- **PY-IC-2** — `@final` on `InputNumberElement` and every codec/adapter leaf.
- **PY-TS-8 / PY-TS-14** — `Literal["input_number"]` / `Literal["changed"]` over
  `str`; every remaining `| None` (`min`/`max`/`step`/`tooltip`) carries an inline
  justification (the discriminated "unbounded" / "no stepper" / "no tooltip"
  states).
- **PY-EH-1 / PY-EH-2** — boundary coercion in the decoder (`ElementWireContext`)
  and in `PatchField`, raising typed errors; internal methods trust the
  invariants.
- **PY-OO-2 (module size ≤ 300, ≤ 3 classes)** — the codec module carries
  `JsonInputNumberDecoder` + `JsonInputNumberEncoder` + `_UpdateValueHandler` (3
  classes, within budget); the element module is one class. No 4+-class module is
  introduced, so no pre-planned split is required. Keep each new module under 300
  lines; `input_number.py` and `input_number_codec.py` both fit the `slider`
  siblings' size.
- **OO ratchet** — run `make update-oo`, stage `.oo-baseline.json` +
  `.oo-audit.jsonl` in the same commit as the source change; do not `--rebaseline`
  to absorb growth.

---

## Local commit hash

Recorded on commit of this branch: see the branch `feat/lux-xs7r.1-input-number-abc`.
