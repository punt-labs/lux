# Extracting the shared `ContinuousEditArbiter` (`lux-ld6y`)

**Status:** implemented. Designed **empirically from the three then-shipped
arbiters**, not from the earlier speculative sketches, and folded exactly as
recommended below.
**Bead:** `lux-ld6y` — the shared continuous-edit extraction, unblocked once all
three non-atomic mutable kinds were migrated and green.
**Scope:** a behavior-preserving refactor (PY-RF-2) that deleted the three
bespoke arbiters and folded all three renderers onto one shared
`ContinuousEditArbiter[T]` in a single change. No new element, no protocol
change, no state-machine change.

**The three pre-fold implementations this design was derived from** — the
bespoke `InputTextArbiter` (`str` carrier), `SliderArbiter` (`float` carrier),
and `ColorPickerArbiter` (arity-4 RGBA `tuple` carrier). They no longer exist as
separate files; the fold replaced all three with the shared module the links
below now point at:

- [`continuous_edit_selection.py`](../../../src/punt_lux/display/renderers/imgui/continuous_edit_selection.py)
  — `ValueAccessor[T]` Protocol + `ContinuousEditArbiter[T]`, the one generic
  arbiter that replaced the three bespoke ones.
- [`continuous_edit_accessors.py`](../../../src/punt_lux/display/renderers/imgui/continuous_edit_accessors.py)
  — `StrValueAccessor` / `FloatValueAccessor` / `ColorValueAccessor`, the three
  `@final` per-carrier leaves.
- [`widget_state.py`](../../../src/punt_lux/scene/widget_state.py) — the one
  `CONTINUOUS_EDIT_*` suffix family (collapsed from the pre-fold `INPUT_*` /
  `SLIDER_*` / `COLOR_*` families) and `get_str` / `get_float` / `get_tuple`.

**Prior sketches (inputs, not the answer):**
[`slider-element-design.md`](./slider-element-design.md) §3.2–3.3 and
[`color-picker-element-design.md`](./color-picker-element-design.md) Part C. Both
were written before the third arbiter existed; this document verifies their
claims against the real three and corrects one.

---

## Top-line verdict: mechanical — with one seam the sketches under-stated, resolved by neutralisation

**The extraction is mechanical.** Diffing the three shipped arbiters
line-for-line confirms the honour/defer/commit/echo control flow is
**byte-identical** across all three. Every genuinely-divergent line reduces to
the value-type carrier `T` and delegates to exactly **two** typed touches — a
buffer *read* and a return *coercion* — which the sketches correctly predicted.

**One correction to the prior claim.** The terse sketch summary —
"the only differences are the WidgetState suffix constants + one buffer-accessor
read + one return coercion" — **under-counts by one seam.** There is a **fourth**
point of `__new__` divergence the sketches folded silently into "suffix
constants": `color_picker`'s buffer lives under its own `COLOR_BUFFER_SUFFIX`,
while `input_text` and `slider` key their buffer off the **bare element id**.
That is a structural divergence in the buffer *key*, not merely a different
suffix string — and it is exactly the candidate "surprise" to check.

**It is not load-bearing, and it does not force a parametrised seam.** The reason
`color_picker` took its own buffer suffix is documented in
[`widget_state.py:44`](../../../src/punt_lux/scene/widget_state.py): "the per-patch
mirror of `widget_value` writes the hex *string* under the bare id, so a buffer
under the bare id would alias a tuple against a hex string on one key." Verified
empirically: **`widget_value()` has no live caller in `src/`** — the per-patch
hex mirror is a *forward-looking premise*, not a wired mechanism. So color's own
suffix guards against an aliasing that does not yet exist. This is precisely the
finding designing off three *working* implementations was meant to surface: the
buffer-key seam is real in the code but not load-bearing in behavior.

**Resolution (recommended):** **neutralise the seam, do not parametrise it.**
All three converge on one shared `CONTINUOUS_EDIT_BUFFER_SUFFIX`, so every
arbiter keys all four slots off a suffix and the buffer-key line stops diverging
entirely. This is *more* mechanical than the sketch's "one accessor plus one
coercion parametrisation" — the buffer key ceases to be a seam at all, rather
than becoming a per-accessor parameter. It is behavior-preserving for the shipped
`input_text` and `slider` (the buffer key is arbiter-internal; nothing outside
the arbiter reads their bare id) and it makes the not-yet-wired mirror safe for
**all three** kinds uniformly instead of only color. Full argument in §4.

**Net:** the `ValueAccessor[T]` seam is exactly **two methods** (`read`,
`coerce`); the buffer-key difference is a cleanup, not a third seam; and the fold
is a behavior-preserving rename + delete governed by the three shipped test
suites and the unchanged ProB model.

---

## 1. The line-by-line diff of the three arbiters

The three arbiters have identical method sets: `__new__`, `resolve`, `observe`,
`commit`, `release`, the `_editing` property, and `_forget_commit`. Below, each
method is classified as **identical** (byte-for-byte, docstrings aside) or the
divergent lines are enumerated exactly.

### 1.1 Methods that are byte-for-byte identical across all three

- **`release`** — identical:

  ```python
  self._state.set(self._editing_key, value=False)
  self._state.discard(self._buffer_key)
  ```

- **`_editing` property body** — identical (`is True` on the editing slot):

  ```python
  return self._state.get(self._editing_key, default=False) is True
  ```

- **`_forget_commit`** — identical:

  ```python
  self._state.discard(self._committed_key)
  self._state.discard(self._commit_hub_key)
  ```

- **The class attribute block** — identical (`_state`, `_buffer_key`,
  `_editing_key`, `_committed_key`, `_commit_hub_key`, all `str`/`WidgetState`).
- **`__new__` scaffolding** — the `super().__new__(cls)`, `self._state = state`,
  and `return self` lines are identical.

Only docstrings differ in wording ("field" / "thumb" / "sub-control"). The code
of these members is the same in all three files.

### 1.2 `__new__` — the key construction (4 divergent lines)

The three suffix assignments differ by family, and the buffer key diverges
structurally:

| Line | `input_text` | `slider` | `color_picker` |
| --- | --- | --- | --- |
| `_buffer_key` | `element_id` | `element_id` | `f"{element_id}{COLOR_BUFFER_SUFFIX}"` |
| `_editing_key` | `…{INPUT_EDITING_SUFFIX}` | `…{SLIDER_EDITING_SUFFIX}` | `…{COLOR_EDITING_SUFFIX}` |
| `_committed_key` | `…{INPUT_COMMITTED_SUFFIX}` | `…{SLIDER_COMMITTED_SUFFIX}` | `…{COLOR_COMMITTED_SUFFIX}` |
| `_commit_hub_key` | `…{INPUT_COMMIT_HUB_SUFFIX}` | `…{SLIDER_COMMIT_HUB_SUFFIX}` | `…{COLOR_COMMIT_HUB_SUFFIX}` |

The three editing/committed/commit-hub suffixes are the expected per-family
divergence (§5 neutralises them). **The `_buffer_key` row is the seam the
sketches under-stated**: `input_text` and `slider` use the bare `element_id`;
`color_picker` uses `f"{element_id}{COLOR_BUFFER_SUFFIX}"`. This is the "third
seam?" question in the mission — analysed and resolved in §4.

### 1.3 `resolve` — the honour/defer/commit/echo body (2 divergent lines)

The control flow is identical in all three:

```python
if self._editing:
    return <BUFFER READ>                         # diverges — line A
committed = self._state.get(self._committed_key)
if committed is not None and hub_value == self._state.get(self._commit_hub_key):
    return <COERCE(committed)>                    # diverges — line B
self._forget_commit()
return hub_value
```

The `committed`/`commit-hub` fetch (`self._state.get(...)`) and the equality
comparison (`hub_value == ...`) go through the **generic, untyped**
`WidgetState.get` and Python `==` — which already work for `str`, `float`, and
`tuple` unchanged. Only two lines carry the value type:

| | Line A — editing-branch buffer read | Line B — committed return coercion |
| --- | --- | --- |
| `input_text` | `self._state.get_str(self._buffer_key)` | `str(committed)` |
| `slider` | `self._state.get_float(self._buffer_key, default=hub_value)` | `float(committed)` |
| `color_picker` | `self._state.get_tuple(self._buffer_key, default=hub_value)` | `RgbaColor.coerce(committed)` |

**Line A carries the miss policy.** `input_text` calls `get_str`, which returns
`""` on a miss and takes **no** default — the empty string is a *real*
cleared-field state that must not fall back to the Hub. `slider` and
`color_picker` call `get_float` / `get_tuple` with `default=hub_value`, so a miss
falls back to the current Hub value. This asymmetry is the mission's "empty-
string miss-policy of input_text vs the hub-value-default of slider/color". It is
**one accessor method, not two** (§3): the accessor's `read` receives
`hub_value`, and each implementation decides whether to use it.

### 1.4 `observe` and `commit` — a parameter-name difference only

Bodies are identical modulo the value type. The one non-type divergence is a
**parameter name**:

| Method | `input_text` | `slider` / `color_picker` |
| --- | --- | --- |
| `observe` | `observe(self, *, edited: bool, text: str)` | `observe(self, *, edited: bool, value: T)` |
| `commit` | `commit(self, text: str, hub_value: str)` | `commit(self, value: T, hub_value: T)` |

`input_text` names its payload `text`; `slider` and `color_picker` name it
`value`. The bodies then read `set(self._buffer_key, text)` vs
`set(self._buffer_key, value)` — same statement, different local name. This is a
**cosmetic divergence the sketches did not mention**; it converges to `value` in
the shared arbiter, and the `input_text` renderer's one call site changes
`observe(edited=changed, text=text)` → `observe(edited=changed, value=text)`. Not
a logic seam.

### 1.5 Type annotations and imports

Every signature annotates the carrier type (`str` / `float` / `Rgba`); these all
become the generic `T`. The pre-fold color arbiter additionally imported
`Rgba, RgbaColor` — the only import divergence; it moved to the
`ColorValueAccessor` (§3), not the shared arbiter.

### 1.6 Diff summary

| Divergence | Where | Absorbed by |
| --- | --- | --- |
| editing/committed/commit-hub suffixes | `__new__` (3 lines) | one `CONTINUOUS_EDIT_*` family (§5) |
| **buffer key: bare id vs own suffix** | `__new__` (1 line) | **neutralise to one buffer suffix (§4)** |
| buffer read + miss policy | `resolve` line A | `ValueAccessor.read` (§2, §3) |
| committed coercion | `resolve` line B | `ValueAccessor.coerce` (§2, §3) |
| payload parameter name `text`/`value` | `observe`, `commit` | rename to `value: T` |
| carrier type annotations | all signatures | generic `T` |
| `Rgba`/`RgbaColor` import | color module only | `ColorValueAccessor` |

**Verdict confirmed:** every divergence is the carrier type or a state-key
string. The only behavioral seam is the two-touch value accessor. The buffer-key
row is a structural divergence that neutralises rather than parametrises. The
extraction is mechanical.

---

## 2. `ValueAccessor[T]` — the seam, derived from the diff (exactly two methods)

The diff shows precisely two typed touches in the whole arbiter, both in
`resolve` (§1.3). `observe`, `commit`, `release`, `_editing`, and `_forget_commit`
use only the untyped `WidgetState.set` / `get` / `discard` and Python `==`, which
are carrier-agnostic. Therefore the accessor Protocol has **two methods, not one,
not three** — derived from the code, not assumed:

```python
from typing import Protocol, runtime_checkable

from punt_lux.scene.widget_state import WidgetState


@runtime_checkable
class ValueAccessor[T](Protocol):
    """The two carrier-typed touches a ContinuousEditArbiter delegates.

    Everything else in the arbiter — the four state slots, the honour/defer/
    commit/echo control flow, value-equality reconciliation — is carrier-
    agnostic. Only the buffer read (with its per-type miss policy) and the
    committed-value coercion carry the type.
    """

    def read(self, state: WidgetState, key: str, hub_value: T) -> T:
        """Return the live buffer this frame; the miss policy is per-type.

        ``input_text`` returns ``""`` on a miss (a real cleared-field state,
        ignoring ``hub_value``); ``slider``/``color_picker`` fall back to
        ``hub_value``.
        """
        ...

    def coerce(self, stored: object) -> T:
        """Coerce a stored committed value to the carrier type for return."""
        ...
```

**Why two, not one.** `read` fetches from `WidgetState` under a key with a
type-specific getter and miss policy; `coerce` casts an already-fetched `object`
(the committed slot, read generically) to `T`. They take different inputs (a
`(state, key, hub_value)` triple vs a raw stored object) and cannot collapse
without the arbiter losing either its generic buffer read or its generic
committed fetch. The code shows two distinct typed lines; the Protocol mirrors
them one-to-one.

**Why not more.** No other line in any of the three arbiters is carrier-typed.
The commit slots are written and compared generically. So two is the honest
minimum *and* maximum — this is the empirical answer to "do NOT assume it's
exactly two if the code shows otherwise": the code shows exactly two.

**PY-TS-6 compliance.** `@runtime_checkable`, a single structural method family,
no abstract base class. Each concrete accessor satisfies it implicitly; tests
assert `isinstance(x, ValueAccessor)` for the family contract. `runtime_checkable`
checks method *presence* only — acceptable here; signature conformance is a
static (pyright) concern.

---

## 3. The three concrete accessors

Three `@final` leaves, one per element, each carrying exactly the per-type
behavior enumerated in the §1.3 diff:

| Accessor | `read(state, key, hub_value)` | miss policy | `coerce(stored)` |
| --- | --- | --- | --- |
| `StrValueAccessor` | `state.get_str(key)` | `""` (ignores `hub_value`) — the cleared-field state | `str(stored)` |
| `FloatValueAccessor` | `state.get_float(key, default=hub_value)` | falls back to `hub_value` | `float(stored)` |
| `ColorValueAccessor` | `state.get_tuple(key, default=hub_value)` | falls back to `hub_value` | `RgbaColor.coerce(stored)` |

```python
from typing import final

from punt_lux.protocol.elements.rgba_color import Rgba, RgbaColor
from punt_lux.scene.widget_state import WidgetState


@final
class StrValueAccessor:
    """Value accessor for input_text — the empty-string miss policy lives here."""

    def read(self, state: WidgetState, key: str, hub_value: str) -> str:
        return state.get_str(key)  # miss -> "" ; a cleared field is a real state

    def coerce(self, stored: object) -> str:
        return str(stored)


@final
class FloatValueAccessor:
    """Value accessor for slider — every float is a value; miss -> hub_value."""

    def read(self, state: WidgetState, key: str, hub_value: float) -> float:
        return state.get_float(key, default=hub_value)

    def coerce(self, stored: object) -> float:
        return float(stored)


@final
class ColorValueAccessor:
    """Value accessor for color_picker — arity-4 RGBA tuple; miss -> hub_value."""

    def read(self, state: WidgetState, key: str, hub_value: Rgba) -> Rgba:
        return state.get_tuple(key, default=hub_value)

    def coerce(self, stored: object) -> Rgba:
        return RgbaColor.coerce(stored)
```

The **entire** empty-string asymmetry is confined to `StrValueAccessor.read` —
the shared arbiter never sees it, which is what keeps the extraction mechanical.
The `get_str` / `get_float` / `get_tuple` getters stay on `WidgetState` unchanged
(the accessors are their only new caller; the type-guarding bodies are already
correct — see [`widget_state.py:64-97`](../../../src/punt_lux/scene/widget_state.py)).

---

## 4. The buffer-key seam — neutralise, do not parametrise

This is the mission's central question: is color's own-suffix buffer (vs
input_text/slider's bare id) a **third seam** the shared arbiter must
parametrise, or is it absorbable?

### 4.1 The empirical finding

Pre-fold, `color_picker`'s buffer lived under its own `COLOR_BUFFER_SUFFIX`
(in the bespoke color arbiter), justified by the comment now carried at
[`widget_state.py`](../../../src/punt_lux/scene/widget_state.py) on
`CONTINUOUS_EDIT_BUFFER_SUFFIX`: a per-patch mirror of `widget_value` writes the
hex *string* under the bare id, so a tuple buffer under the bare id would alias a
tuple against a hex string on one key.

**Verified against the code:** `widget_value()` is *defined* on the elements
(`color_picker.py:208`, `slider.py:281`, etc.) but has **no live caller in
`src/`** — grepping the tree finds only definitions. The per-patch hex mirror is
a **forward-looking premise, not a wired mechanism.** So color's own suffix
guards against an aliasing that does not currently occur. input_text and slider
key their buffer off the bare id and work correctly today precisely because
nothing else writes their bare id.

### 4.2 The three options

- **(a) Own-suffix buffer for all three** — add one shared
  `CONTINUOUS_EDIT_BUFFER_SUFFIX`; every arbiter keys all four slots off a suffix.
  The buffer-key line stops diverging (`f"{id}{CONTINUOUS_EDIT_BUFFER_SUFFIX}"`
  for all three).
- **(b) Bare-id buffer for all three** — drop `COLOR_BUFFER_SUFFIX`; every
  arbiter keys the buffer off the bare id (since the mirror is unwired, color's
  tuple would not currently collide).
- **(c) Parameterise the buffer key per accessor** — the shared arbiter takes the
  buffer suffix (or the whole key) as a `__new__` parameter, and each element
  passes bare-id or own-suffix.

### 4.3 Recommendation: (a), own-suffix for all three

**Why (a).**

1. **It removes the seam entirely.** With one shared buffer suffix, the
   `_buffer_key` line is identical across all three — the fourth `__new__`
   divergence disappears. The extraction becomes *more* mechanical than the
   sketch's "parametrise one accessor" claim: the buffer key is no longer a
   parameter, a seam, or an asymmetry.
2. **It makes the unwired mirror safe uniformly.** The moment the per-patch
   `widget_value` mirror is wired — a plausible future for any of these kinds, not
   just color — a bare-id buffer would alias the mirror for *that* kind. Option
   (a) separates buffer from mirror for **all** kinds, turning color's ad-hoc
   guard into a uniform invariant: the buffer never lives on the bare id, so the
   mirror (whenever wired) never collides with it. Option (b) does the opposite —
   it re-introduces, for all three, exactly the landmine color deliberately
   avoided, optimising for "the mirror isn't wired today."
3. **It keeps the accessor on the right axis.** `ValueAccessor` is about the
   *value type* `T` (read/coerce). A buffer *key* is state-layout policy, not
   value-type policy. Option (c) would smuggle layout policy onto the value seam
   and keep a per-element parameter alive — the wrong axis and one seam more than
   necessary. Reject (c).

**Rejected: (b).** Correct only under the current "mirror unwired" accident;
bakes a latent aliasing into the shared abstraction. Rejected on
future-safety.

**Rejected: (c).** Keeps a seam (a be-spoke buffer key) that (a) eliminates;
places layout policy on the value accessor. Rejected on parsimony and separation
of concerns.

### 4.4 Behavior-preservation for the shipped `input_text` and `slider` (PY-RF-2)

Moving `input_text` and `slider`'s buffer from the bare id to
`CONTINUOUS_EDIT_BUFFER_SUFFIX` **must not** change their behavior. It does not,
because the buffer key is **arbiter-internal**:

- The buffer key is *written* only in `observe`, *read* only in `resolve`'s
  editing branch, *discarded* only in `release`, and *cleared* only in
  `WidgetState.discard_for`. No other code path reads or writes it.
- Nothing outside the arbiter reads an input_text's or slider's bare id: the
  per-patch `widget_value` mirror (the only bare-id writer the comment
  contemplates) is unwired (§4.1), and the legacy renderers that *do* write a
  bare id (`radio`, `combo`, `selectable`, `input_number` —
  [`radio_renderer.py:55`](../../../src/punt_lux/display/renderers/radio_renderer.py),
  etc.) operate on their own distinct elements, never on an input_text or slider.
- `discard_for` is updated to clear the neutral buffer suffix (§5), so a removed
  element still starts clean.

The three arbiter-invariant test suites assert *resolve/observe/release
semantics* (what value the widget receives per frame), not the literal buffer-key
string, so they pass unchanged. `color_picker` already keys its buffer off a
suffix and is green — option (a) is that proven pattern applied to the other two.

---

## 5. Neutralising the `WidgetState` suffix families

Today `WidgetState` carries three per-family suffix sets
([`widget_state.py:25-52`](../../../src/punt_lux/scene/widget_state.py)):

```text
INPUT_EDITING_SUFFIX  INPUT_COMMITTED_SUFFIX  INPUT_COMMIT_HUB_SUFFIX
SLIDER_EDITING_SUFFIX SLIDER_COMMITTED_SUFFIX SLIDER_COMMIT_HUB_SUFFIX
COLOR_BUFFER_SUFFIX   COLOR_EDITING_SUFFIX    COLOR_COMMITTED_SUFFIX   COLOR_COMMIT_HUB_SUFFIX
```

Collapse all three into **one neutral quad** (the buffer suffix included, per
§4):

```text
CONTINUOUS_EDIT_BUFFER_SUFFIX     = ":continuous_edit_buffer"
CONTINUOUS_EDIT_EDITING_SUFFIX    = ":continuous_edit_editing"
CONTINUOUS_EDIT_COMMITTED_SUFFIX  = ":continuous_edit_committed"
CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX = ":continuous_edit_commit_hub"
```

`discard_for` clears the **one** quad (four `discard` calls) in place of the
current ten discards across three families
([`widget_state.py:147-156`](../../../src/punt_lux/scene/widget_state.py)); the
tab-bar (`HONOURED`/`PENDING`) and dialog (`__open`/`__dismissed`) slots are
untouched.

**Safety of one neutral quad.** Element ids are unique within a scene, and the
arbiter is the sole reader/writer of these slots, so no two continuous-edit
elements can collide on a key. A re-added same-id element of a *different* kind
(id `x` was a slider, now an input_text) is handled two ways: `discard_for`
clears the neutral quad on the old element's removal, and even absent removal the
type-guarding getters (`get_str` / `get_float` / `get_tuple`) map a wrong-typed
stored value to their default. No cross-kind contamination is reachable.

`get_str` / `get_float` / `get_tuple` **stay** — the three accessors are their
callers (§3). No getter is added or removed; only the suffix constants and
`discard_for` change.

---

## 6. `ContinuousEditArbiter[T]` — the shared shape

One generic class holds the four slots and the whole honour/defer/commit/echo
control flow, delegating the two typed touches to an injected accessor:

```python
from typing import final

from punt_lux.scene.widget_state import WidgetState


@final
class ContinuousEditArbiter[T]:
    """Resolve a non-atomic mutable widget's value under the commit-echo rule.

    Carrier-agnostic: the four WidgetState slots, value-equality reconciliation,
    and the honour/defer/commit/optimistic-echo discipline are identical for
    text, float, and RGBA-tuple carriers. The two carrier-typed touches — the
    buffer read (with its miss policy) and the committed coercion — are delegated
    to an injected ValueAccessor[T]. Governed by commit_on_idle_reconciliation.tex.
    """

    _state: WidgetState
    _accessor: ValueAccessor[T]
    _buffer_key: str
    _editing_key: str
    _committed_key: str
    _commit_hub_key: str

    def __new__(
        cls, state: WidgetState, element_id: str, accessor: ValueAccessor[T]
    ) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._accessor = accessor
        self._buffer_key = f"{element_id}{WidgetState.CONTINUOUS_EDIT_BUFFER_SUFFIX}"
        self._editing_key = f"{element_id}{WidgetState.CONTINUOUS_EDIT_EDITING_SUFFIX}"
        self._committed_key = (
            f"{element_id}{WidgetState.CONTINUOUS_EDIT_COMMITTED_SUFFIX}"
        )
        self._commit_hub_key = (
            f"{element_id}{WidgetState.CONTINUOUS_EDIT_COMMIT_HUB_SUFFIX}"
        )
        return self

    def resolve(self, hub_value: T) -> T:
        if self._editing:
            return self._accessor.read(self._state, self._buffer_key, hub_value)
        committed = self._state.get(self._committed_key)
        if committed is not None and hub_value == self._state.get(self._commit_hub_key):
            return self._accessor.coerce(committed)
        self._forget_commit()
        return hub_value

    def observe(self, *, edited: bool, value: T) -> None:
        if edited or self._editing:
            self._state.set(self._editing_key, value=True)
            self._state.set(self._buffer_key, value)

    def commit(self, value: T, hub_value: T) -> None:
        self._state.set(self._committed_key, value)
        self._state.set(self._commit_hub_key, hub_value)

    def release(self) -> None:
        self._state.set(self._editing_key, value=False)
        self._state.discard(self._buffer_key)

    @property
    def _editing(self) -> bool:
        return self._state.get(self._editing_key, default=False) is True

    def _forget_commit(self) -> None:
        self._state.discard(self._committed_key)
        self._state.discard(self._commit_hub_key)
```

The bodies are the shipped arbiters verbatim, with `<BUFFER READ>` becoming
`self._accessor.read(...)` and `<COERCE(committed)>` becoming
`self._accessor.coerce(committed)`. Nothing else changes. PEP 695 generic syntax
(`class ContinuousEditArbiter[T]`) is used because the codebase targets Python
3.13+.

The `resolve` docstring keeps the self-contained NaN-reflexivity note the
shipped arbiters carry (value-equality reconciliation assumes `x == x`; a NaN
carrier would never close its echo window). That note is carrier-relevant only
for `float`/`tuple`, but it is correct for all three and belongs on the shared
`resolve` — the per-type *enforcement* of finiteness stays on each element's
`validate()` (§9).

---

## 7. Behavior-preserving fold-in plan (PY-RF-2)

One change, one commit, one PR — wire forward and delete old together; no two
live paths for one reconciliation discipline.

1. **Add the shared modules.** `ContinuousEditArbiter[T]` + `ValueAccessor[T]`
   Protocol in one new module; the three `@final` accessors in a second (§10 for
   module split under PY-OO-2).
2. **Neutralise the suffixes.** Replace the three families with the one
   `CONTINUOUS_EDIT_*` quad and update `discard_for` (§5).
3. **Wire the three renderers.** Each builds the shared arbiter with its accessor:
   - `InputTextRenderer.render`: `ContinuousEditArbiter(self._widget_state,
     elem.id, StrValueAccessor())`; change the one call
     `arbiter.observe(edited=changed, text=text)` → `observe(edited=changed,
     value=text)`.
   - `SliderRenderer.render`: `ContinuousEditArbiter(..., FloatValueAccessor())`;
     the `float(new_val)` int↔float conversion at the `slider_int`/`slider_float`
     seam stays in the renderer.
   - `ColorPickerRenderer.render`: `ContinuousEditArbiter(...,
     ColorValueAccessor())`; the hex↔tuple conversion at the widget seam stays in
     the renderer.
4. **Delete the three bespoke arbiters.** Per the destructive-ops rule, `mv`
   `input_text_selection.py`, `slider_selection.py`, `color_picker_selection.py`
   to `.tmp/`, run the gate, then delete. No behavior lives in them that the
   shared arbiter + accessors do not now carry.
5. **Update the three renderers' imports** to the shared arbiter + accessor.

### 7.1 The regression gate: shipped test suites, behavior assertions unchanged

The extraction is behavior-preserving, so the existing test suites are the
regression gate:

- `tests/render/test_input_text_renderer.py`
- `tests/render/test_slider_renderer.py`
- `tests/render/test_color_picker_renderer.py`
- `tests/test_widget_state.py` — the `WidgetState` accessor and slot-clearing
  suite. It reads the suffix *constants* directly, so it changes with the
  neutralisation (§5), but only in its key layout, never in an outcome.

Plus the Level 1–5 codec/crossing/introspection suites and the Level-4 e2e
scenarios for all three kinds.

**Two classes of test edit, one permitted and one forbidden.** The neutralisation
renames state-key constants and the fold renames the arbiter construction seam,
so *some* test lines must change — but only ever their key layout or their
construction site, never a widget-behavior outcome. Split the "assertion edit"
red flag accordingly:

- **Behavior assertions — MUST NOT change.** Any assertion on a
  `resolve`/`observe`/`release`/`commit` RETURN VALUE or a committed-slot VALUE
  (e.g. `test_input_text_renderer.py`'s `resolve(...) == ...` and
  `ws.get(committed_key) == "same"`/`is None`). If one of these has to change to
  pass, the fold is not behavior-preserving and the extraction has a defect —
  **stop and report it.** This is the merge gate.
- **Key-layout / construction edits — EXPECTED, behavior-preserving.** The suffix
  constant a test reads (`SLIDER_COMMITTED_SUFFIX` → `CONTINUOUS_EDIT_COMMITTED_SUFFIX`),
  the arbiter it constructs (`SliderArbiter(state, id)` →
  `ContinuousEditArbiter(state, id, <Accessor>())`), and the payload keyword
  (`observe(..., text=)` → `observe(..., value=)`) all change; the asserted VALUE
  beside them does not. Fork-era scaffolding is deleted by design:
  `test_widget_state.py::test_slider_suffixes_are_distinct_from_input_suffixes`
  (its own docstring says this extraction deletes it), and the per-kind
  slot-clearing tests collapse into one neutral-quad test.

The distinction is the merge gate: key-layout and construction churn OK; a
behavior-outcome change is NOT OK.

### 7.2 Rollback unit

The fold refactors the reconciliation layer of **three in-production elements**
simultaneously. A regression in the shared arbiter breaks all three; reverting it
restores the three bespoke arbiters. This is one rollback-coherent unit — the
PR-2 boundary the `color_picker` design already scoped
([`color-picker-element-design.md`](./color-picker-element-design.md) Part D).

---

## 8. z-spec: the model is unchanged; update its source-of-record block

The shared arbiter implements
[`docs/commit_on_idle_reconciliation.tex`](../../commit_on_idle_reconciliation.tex)
**unchanged** — it is the *same state machine* for all three carriers. The `.tex`
header already declares the model data-independent over its carrier `[VALUE]`,
naming text, float, and the RGBA tuple as three valid instantiations (the header
comment block and the "Basic Types" section of
[`commit_on_idle_reconciliation.tex`](../../commit_on_idle_reconciliation.tex)).
Folding three implementations into one does not touch a single transition,
invariant, or fidelity variant.

**Two z-spec actions:**

1. **Re-run as the merge gate.** `fuzz -t docs/commit_on_idle_reconciliation.tex`
   clean, and the five ProB goals — `lost=ztrue`, `editing=ztrue & edited=zfalse`,
   `clobbered=ztrue`, `fires>1` (all *not found*), and the deadlock check — at
   `DEFAULT_SETSIZE` 2 and 3, all reporting the verified verdict. Because the fold
   is behavior-preserving, the verdict is unchanged; the re-run is the regression
   proof that the extraction did not perturb the discipline. The fidelity variants
   (defects i/ii/iii) still reproduce when the model is weakened — the model is
   untouched, so fidelity stands.

2. **Rename the source-of-record.** The `.tex` "Source of record" block
   (in the header comment of
   [`commit_on_idle_reconciliation.tex`](../../commit_on_idle_reconciliation.tex))
   currently names the three bespoke arbiter files. After the fold, it names the
   **one** shared arbiter — `display/renderers/imgui/continuous_edit_selection.py
   :: ContinuousEditArbiter` (plus the accessors module) — as the single source of
   record, with the three renderers still listed as the per-kind
   active/deactivate/fire seams. The three per-arbiter entries collapse to one,
   matching the code. This keeps the regression artifact honest: re-run `fuzz` +
   the model-check whenever the shared arbiter changes.

No new spec, no spec extension. Per the recurrence rule, a spec *extension* would
be warranted only if the fold surfaced a genuinely new interleaving — none is
possible, since the fold changes *who* holds the logic, not *what* the logic is.

---

## 9. Validation stays per-element (reconfirmed)

No shared validation helper is extracted, per the standing decision
([`color-picker-element-design.md`](./color-picker-element-design.md) §C.6). The
three elements validate **different value domains** with nothing to factor out:

- `input_text` — no numeric/format check (a `str` is always well-formed).
- `slider` — `min <= max`, in-range `value`, `math.isfinite` on
  `value`/`min`/`max`, printf `format` well-formedness.
- `color_picker` — hex well-formedness (`#` + 6 or 8 hex digits).

The reconciliation-soundness precondition (value-equality needs `x == x`
reflexive) is discharged **differently** per type: `slider` by an active
`math.isfinite` guard, `color_picker` structurally by the hex encoding,
`input_text` trivially. There is no shared surface. Validation is genuinely
element-specific and correctly lives on each element's `validate()`. This
extraction is **arbiter-only**; no `validate()` method is touched.

---

## 10. Module layout and OO

New modules, each within PY-OO-2 (≤ 300 lines, ≤ 3 classes):

- `display/renderers/imgui/continuous_edit_selection.py` — `ValueAccessor[T]`
  Protocol + `ContinuousEditArbiter[T]` (2 classes). The canonical name replaces
  the three bespoke `*_selection.py` modules.
- `display/renderers/imgui/continuous_edit_accessors.py` — `StrValueAccessor`,
  `FloatValueAccessor`, `ColorValueAccessor` (3 classes, `@final` each).

OO posture:

- **Classes own data and behavior** (PY-OO-5): the arbiter owns the four slots
  and the reconciliation; each accessor owns its read+coerce. No module-level
  `_arbiter_resolve(m)` functions.
- **Family shares via Protocol, not base class** (PY-OO-7/PY-TS-6): the three
  accessors satisfy `ValueAccessor` structurally; no `BaseAccessor`.
- **Composition over inheritance** (PY-IC-1): the arbiter *composes* an injected
  accessor; it does not subclass per carrier.
- **No `str`-with-a-comment, minimal `| None`**: the neutral suffix constants are
  `ClassVar[str]` literals; the arbiter has no Optional carrier state (the
  committed slot's absence is the `is None` check on a generic `get`, not a typed
  Optional field).

The OO ratchet (`make check-oo`) must not regress on any touched file; the
extraction *reduces* duplication (three near-identical arbiters → one generic +
three trivial accessors), which pays OO debt down rather than adding it.

---

## Summary of decisions for the direction-check

- **The extraction is mechanical.** The three arbiters' honour/defer/commit/echo
  flow is byte-identical; every divergence is the carrier type or a state-key
  string (§1).
- **`ValueAccessor[T]` has exactly two methods** — `read` (buffer read + miss
  policy) and `coerce` (committed cast) — derived directly from the two
  carrier-typed lines in `resolve`, not assumed (§2).
- **Three `@final` accessors** carry the per-type behavior; the empty-string miss
  policy is confined to `StrValueAccessor.read`, so the shared arbiter never sees
  it (§3).
- **The buffer-key seam is the one thing the sketches under-stated** — color uses
  an own suffix, input_text/slider use the bare id. It guards a **not-yet-wired**
  `widget_value` hex mirror. **Recommendation: neutralise, don't parametrise** —
  one shared `CONTINUOUS_EDIT_BUFFER_SUFFIX` for all three (§4). This is
  behavior-preserving for the shipped input_text/slider (the buffer key is
  arbiter-internal) and makes the future mirror safe uniformly, not just for
  color. Options (b) bare-id-for-all and (c) per-accessor parameter are rejected
  (§4.2–4.3).
- **Neutralise the suffix families** to one `CONTINUOUS_EDIT_*` quad; `discard_for`
  clears the one quad; `get_str`/`get_float`/`get_tuple` stay (§5).
- **Behavior-preserving fold-in** (§7): add shared modules, wire all three
  renderers to `ContinuousEditArbiter` + accessor, delete the three bespoke
  arbiters — one commit. The three shipped test suites are the regression gate;
  **only construction/import edits are permitted, assertion edits are a red
  flag**.
- **z-spec unchanged** (§8): the shared arbiter implements the existing model as
  the same state machine for all three carriers; re-run `fuzz` + the five ProB
  goals as the merge gate, and rename the `.tex` source-of-record block to the one
  shared arbiter.
- **Validation stays per-element** (§9): no shared validation helper; the three
  domains have nothing to factor out.
