# Element migration: `color_picker` onto the Element-ABC / Hub-Display path, and the shared continuous-edit extraction

**Status:** design, awaiting operator direction-check (per
[`README.md`](./README.md) §"The per-element process", step 2).
**Kind:** `color_picker` — interactive value input, element **#3** of the three
non-atomic mutable kinds (`input_text`, `slider`, **`color_picker`**).
**Exemplars:** the shipped `input_text` and `slider` migrations — their ABC
elements
([`input_text.py`](../../../src/punt_lux/protocol/elements/input_text.py),
[`slider.py`](../../../src/punt_lux/protocol/elements/slider.py)), their OO
codecs
([`input_text_codec.py`](../../../src/punt_lux/protocol/elements/input_text_codec.py),
[`slider_codec.py`](../../../src/punt_lux/protocol/elements/slider_codec.py)),
their commit-on-idle arbiters
([`input_text_selection.py`](../../../src/punt_lux/display/renderers/imgui/input_text_selection.py),
[`slider_selection.py`](../../../src/punt_lux/display/renderers/imgui/slider_selection.py)),
their renderers
([`input_text_renderer.py`](../../../src/punt_lux/display/renderers/input_text_renderer.py),
[`slider_renderer.py`](../../../src/punt_lux/display/renderers/slider_renderer.py)),
and the ProB-verified, data-independent reconciliation state machine both
implement
([`input_text_reconciliation.tex`](../../input_text_reconciliation.tex)).
**Tracking:** epic `lux-xs7r`; the shared-abstraction extraction is `lux-ld6y`.
**Slider provenance:** the share-vs-differ analysis in
[`slider-element-design.md`](./slider-element-design.md) §3.2–3.3 is the
starting point for Part C.

---

## Verdicts (read these first)

Three decisions the leader must ratify before implementation. Each is argued in
full below; the headline is here.

**V1 — one arbiter over a tuple-valued carrier, not four coupled single-value
arbiters.** A color is atomic at *every* boundary it crosses: one hex string on
the wire, one widget-level `changed`/active/deactivate signal from ImGui, one
`ValueChanged` on release, one atomic `apply_patch` echo from the Hub. Four
per-component arbiters would fabricate four independent state machines over a
value that is never observed, committed, or echoed component-by-component. The
reconciliation carrier is the RGBA tuple; tuple `==` is elementwise, so
honour/defer/commit/optimistic-echo apply to the whole color atomically. See
[Part B](#part-b--the-key-design-question-one-arbiter-over-a-tuple-carrier).

**V2 — reuse [`input_text_reconciliation.tex`](../../input_text_reconciliation.tex)
unchanged; add no new Z spec.** The model's carrier `[VALUE]` is abstract; a
tuple of finite floats is a valid instantiation of it, exactly as `str` (for
`input_text`) and `float` (for `slider`) are. The tuple introduces **no new
interleaving** — the color is atomic at every boundary, so there is no
partial-echo or per-component race for the model to miss. The one type-specific
proof obligation — tuple `==` is reflexive **iff** no component is `NaN` — is
the per-component finiteness precondition, and for `color_picker` it is
discharged **structurally**: the wire value is a hex string, which cannot encode
`NaN`/`±inf`; the hex→float parse is total onto finite `[0, 1]`. This is
*stronger* than `slider`, which needed a `math.isfinite` check in `validate()`
because raw floats crossed the wire. See
[Part B](#b3-z-spec-reuse-verdict-the-tuple-carrier-is-governed-unchanged).

**V3 — two PRs, split by rollback granularity.** PR-1 migrates `color_picker`
with a bespoke `ColorPickerArbiter` (structurally identical to `SliderArbiter`).
PR-2 (`lux-ld6y`) extracts the shared `ContinuousEditArbiter` and folds all
three arbiters into it. The extraction refactors **two already-shipped,
in-production elements** (`input_text`, `slider`); its blast radius and rollback
semantics differ from a new-kind migration's. Bundling them would force a
regression in the shared refactor to revert a working `color_picker`, and vice
versa. See [Part D](#part-d--pr-boundary).

---

## 1. What crosses the boundary, what is authoritative, what is local

Restating the Hub/Display split for this kind in the designer's own words, per
the direction-check discipline (`README.md` step 1):

- **Hub-authoritative:** the picker's `value` — a hex color string
  (`#RRGGBB` or `#RRGGBBAA`) — plus its static `label` / `alpha` / `picker` /
  `tooltip`. The Hub's copy wins every disagreement. A released edit routes to
  the Hub as a `ValueChanged`; the Hub's built-in state-sync handler
  (`_UpdateValueHandler`) writes the authoritative `value` and re-pushes the
  whole scene.
- **Crosses IPC:** the serialized `ColorPickerElement` (a pickled `_pickled`
  entry in the `SceneMessage`, like every ABC element) and the
  `RemoteEventHandlerInvocation` a display-side release produces.
- **Display-local, never re-pushed:** the *live drag* — the buffer slot and the
  commit-echo slots the arbiter keeps in `WidgetState`. These are the Display's
  per-frame reconciliation state; a whole-tree resend must not clobber a drag in
  progress. The **RGBA float tuple** the ImGui widget works in is a
  Display-local rendering representation: it never crosses the Hub/Display
  boundary. What crosses is the hex string.
- **Never crosses:** ImGui calls. `color_edit3/4` and `color_picker3/4` run only
  on the Display.

`color_picker` is a **non-atomic mutable** control: a single user gesture — a
drag in the saturation-value square, the hue bar, or an RGB slider inside the
widget — passes the color through many intermediate states before release, and
one drag typically moves **several components at once** (a drag in the SV square
moves S and V together, which in RGB terms moves R, G, and B simultaneously).
That is what makes it need the *same class* of continuous-edit reconciliation
`input_text` and `slider` got. A naive "honour `elem.value` every frame" clobbers
the color under the user's cursor the moment a Hub re-push lands mid-drag; a
naive "fire on every `changed`" emits one `ValueChanged` per drag frame. Both are
the exact defects the commit-on-idle model was built to prevent, and they
reproduce on a color picker identically.

The fact that a color drag moves multiple components at once is the empirical
core of verdict V1: the interaction has no per-component granularity to model.

---

## Part A — `color_picker` ABC migration mechanics

Follow `slider` and `input_text` exactly. The concrete surface, class by class,
cited at the line each exemplar's entry sits on today.

### A.1 `ColorPickerElement` on the Element ABC

Replace the legacy frozen dataclass at
[`color_picker.py`](../../../src/punt_lux/protocol/elements/color_picker.py) with
an `Element` ABC subclass, mirroring
[`slider.py`](../../../src/punt_lux/protocol/elements/slider.py) and
[`input_text.py`](../../../src/punt_lux/protocol/elements/input_text.py) line for
line:

- Keyword-only `__new__` with the `RAISING_FACTORY` / `NO_EMIT` sentinels from
  [`abc_di_defaults`](../../../src/punt_lux/protocol/elements/abc_di_defaults.py)
  (`slider.py:64`), `super().__new__(cls, renderer_factory=…, emit=…)`.
- `_kind: Literal["color_picker"]` set in `__new__` (`slider.py:84`); `kind`
  property returns it.
- Typed fields — the operator's directive "typed value + options like
  alpha / picker flags":
  - `_value: str` (default `"#FFFFFF"`). The **wire value is a hex string**, and
    the element stores it as a `str` — the RGBA float tuple is a Display-local
    render detail (§A.5), never a field on the element. This keeps the
    element's wire surface a plain `str`, so `inspect_scene` reads back the hex
    and `ValueChanged` carries the hex on the existing `str` arm of its union
    (§A.6). Total `str`, no Optional.
  - `_alpha: bool` (default `False`) — selects the RGBA (`color_edit4` /
    `color_picker4`) variant and the `#RRGGBBAA` wire form.
  - `_picker: bool` (default `False`) — selects the full picker
    (`color_picker3/4`) over the inline edit (`color_edit3/4`) variant.
  - `alpha` and `picker` stay **two orthogonal `bool`s**, not a four-way
    `Literal`. They are genuinely orthogonal axes — `alpha` is a *channel count*,
    `picker` is a *widget style* — so a `Literal["edit_rgb", "edit_rgba",
    "picker_rgb", "picker_rgba"]` would conflate two independent concerns into
    one enumerated dimension and lose the ability to set them independently.
    This is the same reasoning that keeps `slider._integer` a `bool`
    (`slider.py:125`), applied to two flags: each is a genuine two-state flag,
    not a deferred design decision. **Reject** the merged `Literal`.
  - `_tooltip: str | None` (default `None`) — PY-TS-14 OK, absence is the
    documented "no tooltip" contract, exactly as on `slider`/`input_text`.
  - `_label: str` (default `""`).
- Read-only `@property` accessors for every field (PY-EN-2), plus
  `action -> Literal["changed"]` (`slider.py:130`).
- `_set_<field>` setters for the patch path, using
  [`PatchField`](../../../src/punt_lux/protocol/elements/patch_field.py):
  `_set_value` / `_set_label` via `.as_str`, `_set_alpha` / `_set_picker` via
  `.as_bool`, `_set_tooltip` via `.as_optional_str`. Unlike `slider`, whose
  numeric setters feed a whole-element range re-check in an `apply_patch`
  override (`slider.py:164`), `color_picker` has **no cross-field numeric
  invariant** — each field validates independently — so it needs **no
  `apply_patch` override**. The hex-format invariant is per-field on `value`
  alone and is re-checked by `validate()` before render (§A.7); a hex patch is a
  single field, so the base setter loop suffices. (State this decision
  explicitly so the absence of the override is deliberate, not an omission.)
- `_remote_dispatch_specs()` returning
  `(RemoteDispatchSpec(ValueChanged, self.action, "value_changed"),)` — verbatim
  from `slider.py:180`. This is the whole of the D21 wiring; the inverted wrap
  seam ([DES-041] Decision 5, shipped) needs no `isinstance` branch.
- `to_dict` / `from_dict` delegators to the codec (§A.2), keeping the structural
  `domain.element.Element` Protocol satisfied (`slider.py:260`).
- `validate()` (§A.7) and `resolved_props()` (the Level-5 introspection surface,
  `slider.py:287`) returning `value` / `alpha` / `picker` / `tooltip`.
- `widget_value()` returning `self._value` (the hex string SceneManager mirrors
  into `WidgetState` after a patch), as `slider.py:281`.

### A.2 A dedicated OO codec — `color_picker_codec.py`

A new module `color_picker_codec.py` holding `JsonColorPickerDecoder` +
`JsonColorPickerEncoder` as **classes with methods** — never module-level
`_color_picker_to_dict` / `_color_picker_from_dict` functions (PY-OO-5,
PY-OO-7). This is the pattern
[`slider_codec.py`](../../../src/punt_lux/protocol/elements/slider_codec.py)
establishes and the one the CLAUDE.md "protocol codec functions" debt note
demands new work follow. The legacy `ColorPickerElement.to_dict` /`.from_dict`
(`color_picker.py:32`, `:45`) are the procedural pattern being retired.

- **`JsonColorPickerDecoder`** — constructed once per tier with that tier's
  `renderer_factory` + `emit` + `HandlerDecoder` (`slider_codec.py:81`). Its
  `decode` validates the boundary through
  [`ElementWireContext.for_kind("color_picker")`](../../../src/punt_lux/protocol/elements/element_wire.py)
  (`require_str("id")`, `optional_str("value")`, `optional_bool("alpha"/"picker")`,
  `optional_nullable_str("tooltip")`), constructs the element, **installs the
  built-in `_UpdateValueHandler`** via `add_handler(ValueChanged, …)`, then
  installs any wire-declared `handlers` (`slider_codec.py:112`).
- **`_UpdateValueHandler`** — the serializable built-in that mirrors the
  authoritative value on the Hub when `ValueChanged` fires:
  `self._elem.apply_patch({"value": event.value})` where `event.value` is the
  hex string. Direct analog of `slider`'s `_UpdateValueHandler`
  (`slider_codec.py:32`), with `__reduce__` / `__setstate__` so it crosses the
  wire and the Display can wrap it.
- **`JsonColorPickerEncoder`** — stateless (`__slots__ = ()`), emitting
  `kind` / `id` / `label` / `value`, `alpha` only when `True`, `picker` only
  when `True`, and `tooltip` only when present. It matches the legacy
  `ColorPickerElement.to_dict` (`color_picker.py:32`) byte-for-byte **only in
  the tooltip-absent case** (the corpus case); it now also carries a present
  tooltip (§A.6).
- A `build_standalone_color_picker_handler_decoder` builder (mirroring
  [`build_standalone_slider_handler_decoder`](../../../src/punt_lux/protocol/standalone_slider_handler.py))
  so `ColorPickerElement.from_dict` can decode a handler-less picker with a
  `RaisingPublishSink`, exactly as `slider.py:271` does.

### A.3 Fork wiring points

The forked ABC path is joined at the same six seams `slider` was, each cited at
the line `slider`'s entry sits on today:

1. **`element_factory.py`** — the inbound dispatcher:
   - add `"color_picker"` to `_ABC_KINDS`
     ([`element_factory.py:75`](../../../src/punt_lux/protocol/element_factory.py));
   - add `ColorPickerElement` to `_ABC_LEAF_TYPES` (`element_factory.py:81`);
   - add a `"color_picker": JsonColorPickerDecoder(…).decode` entry to the
     `_decoders` dict (`element_factory.py:162`), wiring
     `build_standalone_color_picker_handler_decoder(publish_sink)`;
   - add `ColorPickerElement` to the legacy-guard `isinstance` union in
     `_decode_legacy` (`element_factory.py:296`) so a picker that reaches the
     codec path fails loud instead of routing wrong.
2. **`encoder_factory.py`** — add
   `(ColorPickerElement, JsonColorPickerEncoder().encode)` to `_DISPATCH`
   ([`encoder_factory.py:43`](../../../src/punt_lux/protocol/encoder_factory.py)).
3. **`protocol/elements/__init__.py`** — add `ColorPickerElement` to the
   ABC-encode `isinstance` union in `_element_to_dict` so its per-kind encoder
   owns tooltip emission (the checkbox/input_text lesson — an omission here
   double-appends or drops the tooltip). `ColorPickerElement` is already in the
   `Element` union
   ([`__init__.py:135`](../../../src/punt_lux/protocol/elements/__init__.py)) and
   `__all__` (`__init__.py:84`); those stay.
4. **`container_abc_gate.py`** — add `"color_picker"` to `_MIGRATED_ABC_KINDS`
   ([`container_abc_gate.py:24`](../../../src/punt_lux/protocol/elements/container_abc_gate.py))
   so an all-ABC `group` / `collapsing_header` / `tab_bar` containing a picker
   forks onto the ABC path rather than the whole subtree falling legacy. Do this
   **only** as part of this migration — the module's own comment
   (`container_abc_gate.py:19`) states a kind joins the set only once its ABC
   decoder is wired.
5. **`display/domain_pump.py`** — add `ColorPickerElement` to `_ABC_TYPES`
   ([`domain_pump.py:36`](../../../src/punt_lux/display/domain_pump.py)) (and its
   import) so an anonymous-id picker raises rather than silently taking the
   `dataclasses.replace` id-synthesis path an ABC instance cannot survive.
6. **`display/renderers/imgui/factory.py`** — add
   `(ColorPickerElement, ImGuiColorPickerRenderer)` to `_DISPATCH`
   ([`factory.py:57`](../../../src/punt_lux/display/renderers/imgui/factory.py)),
   with a new `imgui/color_picker.py` adapter (§A.5).

### A.4 Removal from the legacy registry

Delete the legacy path in the same PR (PY-RF-2 — wire forward, delete old in one
commit; no two live paths for one kind):

- Remove the `register("color_picker", ColorPickerElement, …)` block from
  `InputsRegistry.apply`
  ([`inputs.py:51`](../../../src/punt_lux/protocol/elements/inputs.py)).
- Remove the `(ColorPickerElement, "_color_picker_renderer")` dispatch entry, the
  `_color_picker_renderer` field / construction, and the re-thread entry from
  `ElementRenderer`
  ([`element_renderer.py:95`, `:143`, `:168`, `:181`](../../../src/punt_lux/display/element_renderer.py)).
- The legacy fire-every-change renderer at
  [`color_picker_renderer.py`](../../../src/punt_lux/display/renderers/color_picker_renderer.py)
  is superseded (§A.5) — `mv` it out per the destructive-ops rule, verify, then
  delete.

**Scope boundary on `_color.py`.** The hex helpers in
[`_color.py`](../../../src/punt_lux/display/renderers/_color.py)
(`parse_hex_color`, `parse_rgba`) are **also** consumed by the still-legacy
`text_renderer.py:10` and `spinner_renderer.py:19`. They therefore **stay** —
retiring them rides with the `text`/`spinner` color-styling paths, not with this
migration. This migration introduces its own color value object for the ABC
path (§A.5) and leaves `_color.py` for its remaining legacy consumers. Do **not**
delete `_color.py` in this PR.

### A.5 The renderer, adapter, and the hex↔tuple seam

- A small **`RgbaColor` value object** (frozen, `__slots__`) owns the
  hex↔tuple↔hex conversion the picker needs, replacing free functions with
  methods on the data (PY-OO-5, PY-OO-7): `RgbaColor.from_hex(str) -> Self`
  (total on a validated hex — `validate()` guarantees well-formedness before
  render), `to_hex(*, alpha: bool) -> str` (clamps and formats), and
  `as_tuple() -> tuple[float, float, float, float]` (the 0..1 RGBA the ImGui
  widget consumes). This is the color analog of the `Point2` composition PY-IC-1
  recommends for shared shapes. It is *not* `_color.py`'s free functions
  reheated — those stay for legacy `text`/`spinner`; `RgbaColor` is the ABC
  path's own value type. The legacy renderer's inline `_encode` / `parse_rgba`
  (`color_picker_renderer.py:42`, `:71`) become `RgbaColor` methods.
- A new commit-on-idle `ColorPickerRenderer` in
  `display/renderers/color_picker_renderer.py` (replacing the legacy one),
  shaped exactly like
  [`SliderRenderer`](../../../src/punt_lux/display/renderers/slider_renderer.py):
  build a fresh `ColorPickerArbiter` per element per frame; parse the Hub value
  `RgbaColor.from_hex(elem.value).as_tuple()` and hand
  `arbiter.resolve(hub_tuple)` to `color_edit3/4` or `color_picker3/4` (variant
  chosen by `elem.alpha` / `elem.picker`, as the legacy `_draw`,
  `color_picker_renderer.py:58`); on `is_item_active()` call
  `observe(edited=changed, value=new_tuple)`, else `release()`; on
  `is_item_deactivated_after_edit()` `fire(ValueChanged(value=hex))` — where
  `hex = RgbaColor(new_tuple).to_hex(alpha=elem.alpha)` — **and**
  `commit(new_tuple, hub_tuple)`. The hex↔tuple conversion at the widget seam is
  the color-specific analog of `slider`'s `int`/`float` conversion in its
  `_draw` (`slider_renderer.py:79`): the reconciliation runs on tuples, the wire
  fire carries hex. The commit fire routes through the element's wrapped handler
  for D21 remote dispatch — the Display never runs the real handler locally.
- A new `imgui/color_picker.py` adapter `ImGuiColorPickerRenderer` mirroring
  [`ImGuiSliderRenderer`](../../../src/punt_lux/display/renderers/imgui/slider.py):
  a leaf that paints through `ElementRenderer`'s per-scene
  `color_picker_renderer` plus the shared `apply_tooltip` pass; `begin -> True`,
  `end` a no-op.

### A.6 Protocol touches — one, not two

`slider` made two protocol changes (a `ValueChanged` union widening and a
tooltip activation). `color_picker` makes **only the tooltip one**:

- **(No union widening.)** `ValueChanged.value` is `bool | int | float | str`
  today ([`interaction.py:78`](../../../src/punt_lux/domain/interaction.py)). A
  color commit carries a **hex `str`**, already covered by the existing `str`
  arm (the arm `input_text` uses). No annotation change; refresh only the
  PY-TS-14 justification comment (`interaction.py:76`) to note color→str
  alongside input_text→str. This is a genuine *simplification* over `slider`:
  because color crosses as a string, the wire payload needs no new type.
- **Tooltip activation.** `tooltip` is wire-**dead** on the legacy picker:
  `to_dict` never emits it (`color_picker.py:32`) and `from_dict` never reads it
  (`color_picker.py:45`). This migration **activates** it — the encoder emits
  `tooltip` when present, the decoder reads it — for parity with
  `slider`/`input_text`/`checkbox`. The encoder is therefore byte-identical to
  the legacy `to_dict` only in the tooltip-absent case; a present tooltip is new
  wire. Flag it in the CHANGELOG.

### A.7 Validation — `ColorPickerElement.validate()` (DES-039)

Per [`element-contract.md`](../../target/element-contract.md) §"Validation
Contract" and the "validation rides with migration" rule, `color_picker` gains
its component-appropriate `validate()` as part of this migration. Unlike
`slider`, whose invariant is numeric-range, `color_picker`'s is **hex
well-formedness** — and that check is not a mere paint-safety nicety, it is the
**soundness precondition for reusing the value-equality reconciliation model**
(Part B). Each check returns a `ValidationError(self._id, self._kind, message)`:

1. **`value` is a well-formed hex color.** A leading `#` followed by exactly 6 or
   8 hexadecimal digits. Reject any other shape — wrong length, non-hex digits,
   missing `#`. A malformed hex faults the widget and, worse, cannot be parsed to
   a color the reconciliation can compare (Part B). This is the headline
   invariant.
2. **`value` length agrees with `alpha` (recommended, implementer's call on
   strictness).** When `alpha=True` the picker uses the RGBA variant; a 6-digit
   value is padded to opaque and an 8-digit value supplies its own alpha. Recommend
   **accepting both** (pad `#RRGGBB` → opaque under `alpha`) rather than requiring
   the agent to append `FF`, and reporting only a genuinely malformed hex. Note
   this as a deliberate leniency decision, not an omission.

There is **no `NaN`/finiteness check** and **no `math.isfinite` loop** — the
contrast with `slider.validate()` (`slider.py:249`) is the point. `slider`
needed one because raw floats crossed the wire and an agent could push
`value=NaN`. `color_picker`'s value is a hex string; a well-formed hex parses to
finite `[0, 1]` floats by construction, so check (1) — hex well-formedness —
*is* the per-component finiteness guarantee. It subsumes the reconciliation
precondition. This is the single genuinely color-specific validation concern the
tuple carrier introduces, and it is discharged by the format check the picker
needs anyway.

Aggregate errors (no fail-fast) as `slider.validate()` does. Because there is no
cross-field numeric invariant, no shared `_range_error_messages` predicate and no
`apply_patch` re-check are needed (§A.1).

---

## Part B — the key design question: one arbiter over a tuple carrier

This is the escalation decision. The verdict is stated at the top (V1, V2); here
is the full argument.

### B.1 One arbiter over a tuple carrier, not four coupled single-value arbiters

The choice is between:

- **(chosen)** ONE `ColorPickerArbiter` whose carried value is an RGBA tuple, so
  honour/defer/commit/optimistic-echo apply to the whole color atomically; or
- **(rejected)** FOUR single-value arbiters (one per channel), coupled so they
  defer, commit, and echo together.

Argue from the real interaction, not from the value's shape:

1. **ImGui gives a widget-level signal, not a per-component one.** `color_edit4`
   / `color_picker4` return a single `changed: bool` and a single `ImVec4`; there
   is one `is_item_active()` and one `is_item_deactivated_after_edit()` for the
   *whole* widget (`color_picker_renderer.py:59`). There is no per-channel active
   or deactivate event to feed four arbiters. Four arbiters would have to read the
   same widget-level flags — i.e. move in lockstep — which *is* one arbiter over a
   tuple.
2. **A drag moves several components at once.** A drag in the saturation-value
   square moves S and V together → R, G, B together. The gesture has no
   single-component decomposition to reconcile independently; the natural unit of
   a color edit is the whole color.
3. **The value is atomic at every boundary.** One hex string on the wire; one
   `apply_patch({"value": hex})` on the Hub; one atomic re-push echo. The Hub
   never patches a single channel, so the echo is never partial — the tuple never
   exists in a half-echoed state on the Display. There is nothing for four
   independent arbiters to track that one tuple-carrier arbiter does not.
4. **Tuple `==` is exactly the atomic predicate wanted.** The reconciliation's
   only equality is `hub_value == commit_hub` (`slider_selection.py:82`). For a
   tuple this is Python's elementwise tuple equality: it is `True` only when
   *every* component matches. That is precisely "the whole color has echoed
   back" — the optimistic-echo window closes atomically, exactly as desired. No
   per-component bookkeeping is required to get atomic closure; tuple equality
   delivers it for free.

Four arbiters are therefore not merely more code — they are the wrong model:
they invent independent state for a value that is atomic at the wire, the widget,
the commit, and the echo. **One arbiter over a tuple carrier.**

### B.2 The carrier: an RGBA float tuple, normalized to arity 4

The reconciliation runs on a fixed-arity `tuple[float, float, float, float]` in
`[0, 1]`:

- The renderer parses `elem.value` (hex) → tuple before calling `resolve`, and
  formats the released tuple → hex on commit/fire — the hex↔tuple seam of §A.5.
  This mirrors `slider`, where the renderer passes `elem.value` (already a
  `float`) to `resolve` and converts int↔float at the `_draw` seam
  (`slider_renderer.py:60`, `:79`). The arbiter itself sees only tuples.
- **Normalize to arity 4 regardless of `alpha`** (alpha component defaults to
  `1.0` when `alpha=False`). A fixed arity keeps tuple `==` well-defined — a
  3-tuple never equals a 4-tuple — and keeps the arbiter agnostic to the RGB/RGBA
  variant. The encoder drops the alpha channel from the hex when `alpha=False`
  (`#RRGGBB`), so the wire form stays correct; only the Display-local carrier is
  always length 4.

**Rejected alternative — a hex-string reconciliation carrier.** One could keep
the reconciliation carrier the hex string (making the arbiter *literally*
`input_text`'s `str` carrier, no tuple, no finiteness concern at all) and use the
tuple only for the live-drag buffer. It is sound, but it **splits the arbiter's
key type (`str`) from its buffer type (`tuple`)** — a split neither `input_text`
nor `slider` has (in both, buffer and key are the same type). That split would
force the shared `ContinuousEditArbiter` (Part C) to carry *two* type seams
instead of one, defeating the single-accessor extraction that doing `color_picker`
third is meant to enable. It also introduces a hex-quantization mismatch between
the full-precision committed tuple displayed optimistically and the 8-bit echo.
The uniform tuple carrier is preferred precisely because it keeps the extraction
to one seam. Noted so the choice is deliberate.

### B.3 Z-spec reuse verdict: the tuple carrier is governed unchanged

The question the leader must be able to defend: does the data-independent
[`input_text_reconciliation.tex`](../../input_text_reconciliation.tex) govern a
**tuple** carrier unchanged, or does the tuple introduce a genuinely new
interleaving or invariant needing a spec extension?

**It governs unchanged. No new spec.** The argument is three-part and each part
must hold:

1. **The model's carrier is abstract.** The spec's basic type is `[VALUE]`
   (`input_text_reconciliation.tex` §"Basic Types"), which ProB enumerates over a
   bounded set; every operation reasons purely about value *equality* (`disp =
   committed`, `hub = committed`) and value *movement* (the honour frames, the
   echo, the agent push). The `.tex` header already declares the model
   "type-agnostic — its carrier `[VALUE]` stands for the text an input_text holds
   or the float a slider holds — so it governs BOTH arbiters unchanged." A tuple
   of finite floats is a third valid instantiation of `[VALUE]`, exactly as `str`
   and `float` are. Nothing in the transition relation or the five invariants
   mentions the carrier's internal structure.
2. **The tuple introduces no new interleaving.** A new interleaving would need a
   boundary at which the color is observed, committed, or echoed
   component-by-component — a partial-echo or per-component race. There is none
   (§B.1): the color is atomic at the wire, the widget, the commit, and the echo.
   The model already enumerates every interleaving of focus, keystroke, commit,
   echo, and re-focus over one atomic value; a wider atomic value adds no
   reachable state. In particular the model's `HubEcho`
   (`input_text_reconciliation.tex` §"The Hub Value") sets `hub' = committed`
   atomically — which for a tuple is the whole color arriving at once, exactly the
   atomic `apply_patch` the Hub performs. There is no half-echoed tuple state for
   the model to be blind to.
3. **The one type-specific proof obligation is discharged.** The soundness of
   value-equality reconciliation rests on **reflexivity**: a committed value
   equals itself, so its echo closes the window. Tuple `==` is reflexive **iff no
   component is `NaN`** (`NaN` is the one float where `x == x` is `False`). This is
   the per-component finiteness precondition the tuple carrier makes explicit. For
   `color_picker` it is discharged **structurally**: the wire value is a hex
   string, which cannot encode `NaN`/`±inf`; the hex→float parse is total onto
   finite `[0, 1]`; and `validate()`'s hex-well-formedness check (§A.7) rejects
   any value that would not parse. So no non-finite component is reachable, tuple
   `==` stays reflexive, and the `HubEcho`-closes-the-window proof carries over
   verbatim. This is *stronger* than `slider`, whose finiteness precondition
   required an active `math.isfinite` guard (`slider.py:197`) because raw floats
   crossed the wire; `color_picker` gets it for free from the hex encoding.

Therefore this migration **reuses
[`input_text_reconciliation.tex`](../../input_text_reconciliation.tex) as its
governing specification and adds no new Z spec.** The merge gate for the
reconciliation logic is re-running that model — `fuzz -t` clean, and the five
ProB goals (`lost`, `editing∧¬edited`, `clobbered`, `fires>1`, deadlock) all
reporting the verified verdict at `DEFAULT_SETSIZE` 2 and 3 — because the model
is the shared discipline all three arbiters implement. The `.tex` header comment
should be updated to name the tuple carrier alongside text and float, and to note
that the tuple's finiteness precondition is discharged structurally by the hex
encoding.

**When this verdict would flip.** If implementation surfaced a color interaction
that is *not* atomic at some boundary — e.g. a future widget that streams
per-component patches to the Hub, so an echo could arrive with some components
updated and others not — that would be a genuinely new interleaving (a partial
echo) and the recurrence signal to *extend* the spec (add a partial-echo
transition and re-check reflexivity of the honour predicate under it). None is
anticipated: `color_edit`/`color_picker` commit the whole color on release and
the Hub patches `value` atomically. The design's claim is that no such
non-atomic boundary exists, and §B.1 is the rigorous positive.

### B.4 Known edges — F1 and F2 apply identically

The two documented non-loss limits from
[`input_text_reconciliation.tex`](../../input_text_reconciliation.tex) §"Scope
and Known Limitations" apply to `color_picker` unchanged, deferred to the
echo-token scheme (`lux-ld6y`) exactly as for the other two:

- **F1 — two commits within one echo round-trip.** A picker released, re-grabbed,
  and released again before the first echo returns holds only the second commit
  in its single slot pair; the display can transiently revert to the intermediate
  authoritative Hub color — a one-frame flicker between two committed colors —
  before the second commit's echo lands. Transient display artifact, not data
  loss. Sub-millisecond on localhost.
- **F2 — agent drives the Hub back to the exact commit-time color.** Masked as the
  pending echo under value-equality reconciliation, until the color next moves off
  that value. As with `slider`, two independent drag positions comparing equal
  under tuple `==` is *less* reachable than two strings colliding — F2 is even
  more benign for a multi-component tuple, since all four components must match
  bit-for-bit.

---

## Part C — the shared extraction: `ContinuousEditArbiter` (`lux-ld6y`)

With **three** concrete non-atomic mutable elements in hand
(`InputTextArbiter`, `SliderArbiter`, and the new `ColorPickerArbiter`), the
Rule of Three is satisfied and the shared abstraction is extracted. This part
designs it; Part D recommends it ship as its own PR.

### C.1 What all three share (already proven mechanical)

Everything below is byte-for-byte the same control flow across the three
arbiters; only the carried value's type differs. The
[`slider-element-design.md`](./slider-element-design.md) §3.2 share table
enumerated it for two; the third confirms it:

| Shared element | `input_text` | `slider` | `color_picker` |
| --- | --- | --- | --- |
| Four slots keyed off the element id (buffer / editing / committed / commit-hub) | yes | yes | yes |
| Slots survive a whole-UI re-push (a commit may be in flight across the resend) | yes | yes | yes |
| Slots cleared in `WidgetState.discard_for` on removal | yes | yes | yes |
| `observe` defers **only** on `edited or already-editing` — never on mere focus/grab | yes | yes | yes |
| `commit(v, hub)` records committed + commit-time hub; does **not** clear editing | yes | yes | yes |
| `release` clears editing + drops buffer; keeps the commit record | yes | yes | yes |
| `resolve`: editing → buffer; elif committed set and `hub == commit-hub` → committed; else forget + hub | yes | yes | yes |
| Reconciliation by **value equality alone** — no echo token, single-slot latest-commit | yes | yes | yes |
| The two non-loss limits (F1 flicker, F2 same-value masking) | yes | yes | yes |
| Governed by [`input_text_reconciliation.tex`](../../input_text_reconciliation.tex) | yes | yes | yes |

The `resolve`/`observe`/`commit`/`release`/`_forget_commit`/`_editing` bodies of
[`input_text_selection.py`](../../../src/punt_lux/display/renderers/imgui/input_text_selection.py)
and
[`slider_selection.py`](../../../src/punt_lux/display/renderers/imgui/slider_selection.py)
are already identical line-for-line except for **one** typed line each.

### C.2 The single seam: the buffer value accessor

Reading the two shipped arbiters, the **only** type-specific line in each is the
buffer read inside `resolve`:

- `input_text`: `self._state.get_str(self._buffer_key)`
  ([`input_text_selection.py:73`](../../../src/punt_lux/display/renderers/imgui/input_text_selection.py))
  — returns `""` on a miss; the empty string is a *real* cleared-field state.
- `slider`: `self._state.get_float(self._buffer_key, default=hub_value)`
  ([`slider_selection.py:80`](../../../src/punt_lux/display/renderers/imgui/slider_selection.py))
  — a miss falls back to the current Hub value.

Plus the tiny return cast (`str(committed)` / `float(committed)`,
`input_text_selection.py:76` / `slider_selection.py:83`). The
`committed`/`commit-hub` slots are stored and compared through the **generic**,
untyped `WidgetState.get` and Python `==` (`input_text_selection.py:74–75`) —
which already works for `str`, `float`, and `tuple` without change. So the whole
type surface of the arbiter is **one accessor plus one coercion**.

Extract a `ContinuousEditArbiter` parameterised by a small **value-accessor**
strategy (a `runtime_checkable` Protocol, PY-TS-6 — a structural single-method
family, not a base class):

```text
ValueAccessor[T]:
    read(state, key, hub_value) -> T      # the buffer read; miss policy is per-type
    coerce(stored) -> T                   # the resolve return cast
```

Three implementations, one per element, each a `@final` leaf:

| Accessor | `read` on a miss | `coerce` | Empty-value policy |
| --- | --- | --- | --- |
| `StrValueAccessor` | `get_str(key)` → `""` (ignores `hub_value`) | `str(stored)` | `""` is a real edited state — the special case lives **here** |
| `FloatValueAccessor` | `get_float(key, default=hub_value)` | `float(stored)` | none — every float is a value |
| `ColorValueAccessor` | `get_tuple(key, default=hub_value)` | `RgbaColor.coerce(stored)` (arity-4 tuple) | none — every color is a value |

The arbiter holds the four slots and the whole honour/defer/commit/echo control
flow; it delegates exactly the two typed touches to its injected accessor.
`observe(*, edited, value: T)`, `commit(value: T, hub_value: T)`,
`resolve(hub_value: T) -> T` all carry the generic `T`.

### C.3 Exactly what each element passes in

- **`input_text`** passes `StrValueAccessor()`. `resolve` receives `elem.value`
  (a `str`). The empty-string special case — the `test_editing_keeps_a_cleared_field_empty`
  behavior — is entirely inside `StrValueAccessor.read` (return `""` on a miss,
  ignoring `hub_value`); it does not leak into the shared arbiter.
- **`slider`** passes `FloatValueAccessor()`. `resolve` receives `elem.value` (a
  `float`); the renderer converts int↔float at the `slider_int`/`slider_float`
  seam as today (`slider_renderer.py:79`).
- **`color_picker`** passes `ColorValueAccessor()`. `resolve` receives the parsed
  hub tuple; the renderer converts hex↔tuple at the `color_edit`/`color_picker`
  seam (§A.5).

### C.4 Is the extraction mechanical? Yes, empty-string asymmetry isolated

The extraction is mechanical, and the *one* place it is not purely uniform is
named precisely: **`input_text`'s empty-string default.** `input_text`'s buffer
default is `""` — a valid edited state (a cleared field), which must **not** fall
back to the Hub value — whereas `slider` and `color_picker` fall back to the Hub
value on a miss. This is the single genuinely non-uniform behavior. It is
absorbed cleanly into `StrValueAccessor.read`, which ignores `hub_value` and
returns `""`; the shared arbiter never sees the asymmetry. So the extraction is
mechanical **provided** the accessor abstraction carries the miss policy — which
it does, in one method on one strategy. This confirms the
[`slider-element-design.md`](./slider-element-design.md) §3.3 claim that #3 is a
"mechanical parametrisation and not a redesign": the parametrisation is one
`ValueAccessor` per element, and the only non-boilerplate content is
`StrValueAccessor`'s empty-string policy.

### C.5 Neutralise the `WidgetState` suffix constants

Today `WidgetState` carries two parallel triples —
`INPUT_EDITING_SUFFIX` / `INPUT_COMMITTED_SUFFIX` / `INPUT_COMMIT_HUB_SUFFIX`
([`widget_state.py:24`](../../../src/punt_lux/scene/widget_state.py)) and
`SLIDER_EDITING_SUFFIX` / `SLIDER_COMMITTED_SUFFIX` / `SLIDER_COMMIT_HUB_SUFFIX`
(`widget_state.py:36`) — each cleared in `discard_for` (`widget_state.py:96–101`).
A bespoke `color_picker` PR (Part D, PR-1) adds a third `COLOR_*` triple; the
extraction PR (PR-2) then collapses all three into **one neutral triple**:

```text
CONTINUOUS_EDIT_EDITING_SUFFIX
CONTINUOUS_EDIT_COMMITTED_SUFFIX
CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX
```

with `discard_for` clearing the one triple instead of two/three. Because no two
of these elements ever share an id, one neutral triple is safe; the rename is
mechanical (touch `widget_state.py` and the three arbiters). Add `get_tuple` to
`WidgetState` alongside `get_str`/`get_float` (the `ColorValueAccessor` buffer
read) — returns `default` if absent or not an arity-3/4 tuple of finite floats,
the color analog of `get_float` (`widget_state.py:55`).

### C.6 Shared numeric-validation helper? No — validation stays per-element

The `slider` PR drew several Copilot rounds on numeric/format validation
(min≤max, in-range, finiteness, printf-format well-formedness). Assess whether a
shared validation helper is worth extracting alongside the arbiter: **no.**

- The three elements validate **different value domains**: `input_text` a `str`
  (no numeric check at all), `slider` a numeric range + printf format, `color_picker`
  a hex-string format. There is essentially no shared validation surface —
  `slider`'s `math.isfinite`/range/printf checks and `color_picker`'s hex-format
  check have nothing in common to factor out.
- The reconciliation-soundness precondition is discharged **differently** per
  type: `slider` by an active `math.isfinite` guard, `color_picker` structurally
  by the hex encoding, `input_text` trivially (strings can't be `NaN`). No shared
  helper.

Validation is genuinely element-specific and correctly lives on each element's
`validate()`. Recommend **not** extracting a shared validation helper as part of
`lux-ld6y`. If a future `input_number` migration shares `slider`'s numeric
checks, extract a numeric-validation helper **then**, under its own Rule of Three
for validation — separate from the arbiter extraction. Keep this PR's validation
scope to `color_picker`'s hex-format check (§A.7).

---

## Part D — PR boundary

**Recommendation: two PRs.**

- **PR-1 — migrate `color_picker` onto the ABC path with a bespoke
  `ColorPickerArbiter`.** Everything in Part A, plus a `ColorPickerArbiter` in
  `display/renderers/imgui/color_picker_selection.py` structurally identical to
  `SliderArbiter` (tuple carrier, a `COLOR_*` `WidgetState` triple). Rollback
  unit: the new kind. On merge, three concrete non-atomic arbiters exist — the
  Rule-of-Three precondition for the extraction is met.
- **PR-2 — extract `ContinuousEditArbiter` (`lux-ld6y`).** Everything in Part C:
  fold `InputTextArbiter` + `SliderArbiter` + `ColorPickerArbiter` into the one
  shared abstraction, introduce the three `ValueAccessor` strategies, neutralise
  the `INPUT_*`/`SLIDER_*`/`COLOR_*` suffixes to `CONTINUOUS_EDIT_*`. Rollback
  unit: the refactor of the reconciliation layer across all three elements.

**Justification by rollback granularity** (CLAUDE.md: "split by rollback
granularity, not size"). The deciding question is "if this broke production, what
reverts together?"

- PR-1 affects **only the new `color_picker` kind**. A regression in it reverts
  the new kind; `input_text` and `slider` are untouched.
- PR-2 refactors **two already-shipped, in-production elements** (`input_text`,
  `slider`) plus `color_picker`. A regression in the shared arbiter breaks all
  three simultaneously; reverting it restores three bespoke arbiters.

These are two distinct rollback-coherent units with different blast radii.
Bundling them means a bug in the shared-arbiter refactor forces reverting a
working `color_picker` migration (and a bug in the `color_picker` migration forces
touching the shared refactor). CLAUDE.md names "independent rollback capability"
a valid split reason, and a behavior-preserving refactor (PY-RF-2) that touches
shipped elements has a materially different risk profile from a new-kind
migration — it should ship as its own rollback unit.

**The one-PR counter, acknowledged.** Doing `color_picker` straight onto the
shared arbiter avoids a throwaway bespoke `ColorPickerArbiter` and keeps the
Rule-of-Three extraction coincident with the arrival of the third case. The
throwaway cost is small — the bespoke arbiter is structurally identical to the
shared one, so folding it in is a near-rename — and is outweighed by the
rollback-coupling cost of bundling a two-element refactor with a new-element
migration. The `lux-ld6y` bead already scopes the extraction as its own unit of
work. **Recommend PR-1 then PR-2**; the leader escalates the boundary to the
operator given the standing "general solution or not at all" directive, which
this honours: the bespoke arbiter is a structurally-identical placeholder that
never ships as the permanent state — PR-2 immediately unifies all three into the
one shared abstraction.

---

## Summary of decisions for the direction-check

- **One arbiter over an RGBA tuple carrier** (V1). The color is atomic at the
  wire, the widget, the commit, and the echo; four per-component arbiters would
  invent state for a value with no per-component interaction. Tuple `==` gives
  atomic echo-window closure for free.
- **Reuse [`input_text_reconciliation.tex`](../../input_text_reconciliation.tex)
  unchanged; no new Z spec** (V2). The carrier `[VALUE]` is abstract; the tuple
  adds no new interleaving (atomic at every boundary); the per-component
  finiteness precondition is discharged **structurally** by the hex encoding —
  stronger than `slider`'s active `math.isfinite` guard. Re-run `fuzz` + the five
  ProB goals as the merge gate.
- **One protocol touch, not two.** No `ValueChanged` union widening (color rides
  the existing `str` arm); activate the previously wire-dead `tooltip`.
- **`validate()` checks hex well-formedness** — which *is* the reconciliation
  soundness precondition, not a separate nicety. No finiteness loop, no
  `apply_patch` override (no cross-field numeric invariant).
- **Introduce an `RgbaColor` value object** for the ABC path's hex↔tuple seam
  (PY-OO-5/7); leave `_color.py`'s free functions for their still-legacy
  `text`/`spinner` consumers.
- **Extract `ContinuousEditArbiter` parameterised by one `ValueAccessor` seam**
  (Part C). Each element passes its accessor (`StrValueAccessor` /
  `FloatValueAccessor` / `ColorValueAccessor`); the extraction is mechanical, with
  the empty-string asymmetry isolated to `StrValueAccessor`. Neutralise the
  `WidgetState` suffixes to `CONTINUOUS_EDIT_*`. Validation stays per-element — no
  shared validation helper.
- **Two PRs, split by rollback granularity** (V3): PR-1 migrates `color_picker`
  (bespoke arbiter); PR-2 (`lux-ld6y`) extracts the shared arbiter across all
  three shipped elements.
