# Migrating `progress` onto the Element-ABC / HubDisplay Path — Step 1

**Status:** design + verification plan for operator direction-check. No code.
**Type:** migration design (Batch 1, first kind).
**Element:** `progress` — a display-only leaf.
**Exemplar copied:** `TextElement` — the display-only leaf already on the ABC path.
**Ground truth:** `docs/architecture/target/{target,ui-model,element-contract,introspection-api}.md`
and the code cited inline.

This is step 1 of the epic in `docs/architecture/element-migration-audit.md`. Its
two jobs are (1) establish the display-only-leaf migration pattern that Batch 1's
remaining kinds (image, separator, spinner, markdown) will copy, and (2) build the
introspection primitive that makes every subsequent migration PR
*programmatically* verifiable — so a test asserts "this element flipped to the ABC
path and its value reads back," and manual testing only confirms the pixels.

It goes to the operator for a direction-check **before** any implementation. The
open questions in §6 are the direction-check items.

---

## 1. Understanding restated

### 1.1 What a display-only leaf is, in this architecture

The target model is one authority. Clients submit UI to the Hub; the Hub decodes
it into typed UI objects and installs them in `HubDisplay`, which is the
authoritative store for state, ownership, and handler dispatch; the Display holds
a full replica used only for rendering and input capture; after a change the Hub
re-sends the whole affected UI and the Display replaces its copy
(`target.md:24`–`:39`). The load-bearing boundary rule: **UI state crosses IPC;
render calls do not** (`target.md:63`–`:71`). Scene trees and serialized element
objects cross the wire; ImGui calls stay local to the Display.

A `progress` bar is *passive display content* — the "basic display elements"
family, whose handler expectation is explicitly "no app-facing handlers"
(`element-contract.md:72`, `:233`). It has state (a fill fraction, an overlay
label) and it renders deterministically from that state, but a user cannot
interact with it. Nobody clicks a progress bar; it fires no events; no business
logic hangs off it.

### 1.2 What crosses the boundary, what is authoritative, what is local

For `progress` specifically:

- **Crosses the Hub→Display boundary:** the serialized element object — its
  `id`, `kind`, `fraction`, `label`, `tooltip`. This is UI state. When the
  fraction changes, the whole affected UI is re-sent and the Display replaces its
  copy (`target.md:35`, `ui-model.md:173`–`:184`).
- **Hub-authoritative:** the element's *state* — the current `fraction` and
  `label`. The Hub owns it; the Display never mutates it locally. Because a
  progress bar has no interaction, there is no interaction leg back to the Hub —
  the Display never needs to tell the Hub anything about a progress bar.
- **Display-local:** only the ImGui paint. `imgui.progress_bar(fraction, size,
  overlay)` runs on the Display against its replica
  (`display/renderers/progress_renderer.py:21`–`:23`). Render calls do not cross
  the wire.

### 1.3 Why a display-only leaf needs `render`/`id`/`_children`/`apply_patch` but NOT the handler/wrap machinery

The Element ABC (`domain/element_abc.py:49`) carries a wide surface, but a
display-only leaf uses only part of it:

| ABC member | Progress needs it? | Why |
|---|---|---|
| `id` (abstract property, `element_abc.py:100`) | **Yes** | The only abstract member. Every element must have a stable identity within its scene (`element-contract.md:44`); `HubDisplay` indexes and resolves by it (`domain/display.py:88`, `:349`). |
| `render()` (template, `element_abc.py:105`) | **Yes, inherited** | Never overridden. For a leaf it calls `renderer_factory(self)` then `renderer.render()`; the empty-children branch is taken. |
| `_children()` (`element_abc.py:119`) | **Yes, the empty default** | A leaf has no children. It inherits `return ()` and never overrides — exactly as `TextElement` does. |
| `apply_patch()` (`element_abc.py:124`) | **Yes, inherited** | The in-place mutation path that replaces the frozen-dataclass `replace(...)` call. It dispatches each patch key to a `_set_<key>` setter, which the element must provide. |
| handler registry — `add_handler`/`fire` (`element_abc.py:151`, `:177`) | **Present but unused** | A progress bar registers no handlers and fires no events. The empty `_handlers` dict costs nothing (audit Decision (a), `element-migration-audit.md:304`). |
| `wrap_handlers_for_remote()` (`element_abc.py:213`) | **Present but a no-op for progress** | The D21 two-tier seam wraps `ButtonElement`/`CheckboxElement` handlers for remote dispatch. It branches on `isinstance` (`element_abc.py:231`, `:248`); `progress` matches neither branch, and its empty `_children()` means the recursion terminates immediately. Progress is never added to that method. |
| observer surface — `mark_removed`/`add_observer` (`element_abc.py:284`, `:297`) | **Present but unused** | Used by composites to cascade child removal. A leaf with no children never drives it. |

The rule in one line: **a display-only leaf needs the ABC's identity, render
template, empty-children hook, and patch/setter surface; it inherits — but does
not exercise — the handler, wrap, and observer machinery.** That is precisely the
shape the audit calls the "display-only leaf" and names `TextElement` as its
template (`element-migration-audit.md:59`, `:147`–`:164`).

### 1.4 The analogy to Text, made explicit

`TextElement` (`text.py:47`) is the proof that this shape works:

- It subclasses `Element` with keyword-only `__new__` and sentinel
  `renderer_factory`/`emit` defaults (`text.py:68`–`:79`).
- It implements exactly one abstract member, `id` (`text.py:90`–`:93`).
- It does **not** override `_children()` — it inherits the empty leaf default.
- It provides `_set_content`/`_set_style`/`_set_tooltip`/`_set_color` setters so
  the inherited `apply_patch` works (`text.py:142`–`:156`).
- It keeps `to_dict`/`from_dict` delegators so the structural
  `domain.element.Element` Protocol still holds (`text.py:160`–`:173`).
- It registers no handlers and appears in no branch of
  `wrap_handlers_for_remote`.

`progress` is the same shape with a different field set. Text carries
`{content, style, tooltip, color}`; progress carries `{fraction, label,
tooltip}`. Everything structural is identical. That is why this migration is
"copy the Text exemplar" and not "invent a new pattern."

### 1.5 One subtlety the operator must confirm (see §6, Q3)

For a display-only leaf, migrating onto the ABC does **not** change how pixels get
painted today. The live paint path is `ElementRenderer.render_element` →
`_dispatch_native(elem)`, which matches the element by `isinstance` against
`_NATIVE_DISPATCH` and calls `ProgressRenderer.render(elem)`
(`element_renderer.py:152`–`:168`, `:209`–`:219`). That renderer reads
`elem.fraction` and `elem.label`
(`display/renderers/progress_renderer.py:22`). Because the ABC subclass exposes
those as properties, the legacy renderer keeps working unchanged. The ABC's own
`render()` template method (`element_abc.py:105`) is **not** the live paint path
for progress yet — retiring the `_dispatch_native`/`_RENDERERS` dispatch in favor
of `elem.render()` is a later batch (`element-migration-audit.md:221`–`:230`,
Batch 7).

So "flipped to the ABC path" for a display-only leaf means: the element *object*
is now an `Element`-ABC subclass, it is mutated via `apply_patch`/`_set_*` instead
of `dataclasses.replace`, it is encoded/decoded through the per-kind ABC codecs,
and it is routed into `HubDisplay` (the domain `Display`) via the pump's
`apply` path instead of falling through the dataclass branch. It does **not** mean
ImGui paint now flows through `Element.render()`. This is exactly the kind of
subtle-but-load-bearing distinction the operator flagged; §6 Q3 asks for
confirmation that this is the intended meaning of "migrated" for a leaf.

---

## 2. The `ProgressElement` ABC design

### 2.1 Before (legacy) and after (ABC)

The current `ProgressElement` is a frozen dataclass with a hand-rolled codec
(`protocol/elements/progress.py:14`–`:42`):

```python
@dataclass(frozen=True, slots=True)
class ProgressElement:
    id: str
    kind: Literal["progress"] = "progress"
    fraction: float = 0.0
    label: str = ""
    tooltip: str | None = None
    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, d): ...
```

The after-shape mirrors `TextElement` piece for piece. The codec body moves to a
sibling `progress_codec.py` (mirroring `text_codec.py`); the element keeps only
delegators.

### 2.2 The exact ABC subclass shape, mapped to Text file:line

| Piece | `ProgressElement` (target) | Mirrors `TextElement` at |
|---|---|---|
| Base + keyword-only `__new__` with sentinel `renderer_factory`/`emit` | `class ProgressElement(Element)`, `__new__(cls, *, renderer_factory=_RAISING_FACTORY, emit=_no_emit, id, fraction=0.0, label="", tooltip=None)` | `text.py:47`, `:68`–`:86` |
| Module sentinels | reuse the same `_RAISING_FACTORY = RaisingRendererFactory()` and `_no_emit` Null-Object pattern | `text.py:40`, `:43`–`:44` |
| `id` abstract property | `@property def id(self) -> str: return self._id` | `text.py:90`–`:93` |
| `kind` property | `@property def kind(self) -> Literal["progress"]: return self._kind` | `text.py:96`–`:98` |
| state properties | `fraction -> float`, `label -> str`, `tooltip -> str \| None` (read-only) | `text.py:101`–`:118` |
| `_children()` | **inherited** — leaf, empty default, not overridden | `element_abc.py:119` (Text also inherits) |
| `apply_patch()` | **inherited** from the ABC | `element_abc.py:124` (Text also inherits) |
| setters for patch fields | `_set_fraction`, `_set_label`, `_set_tooltip` (each validates at the boundary per PY-EH-1, then assigns) | `text.py:142`–`:156` |
| boundary validators | `_float_or_raise`, `_str_or_raise`, `_opt_str_or_raise` static helpers | `text.py:126`–`:140` (`_str_or_raise`, `_opt_str_or_raise`) |
| `to_dict` delegator | `return JsonProgressEncoder().encode(self)` | `text.py:160`–`:162` |
| `from_dict` delegator | construct `JsonProgressDecoder(...)` and `return cast("Self", decoder.decode(d))` | `text.py:164`–`:173` |

### 2.3 What moves where

- **`progress.py`** — becomes the ABC subclass above. Fields become private
  attributes with read-only properties. Setters added. Dataclass decorator
  removed.
- **`progress_codec.py`** (new) — `JsonProgressEncoder` + `JsonProgressDecoder`,
  mirroring `text_codec.py:29`–`:103`. The decoder takes the tier's
  `renderer_factory` + `emit` + `element_cls` and builds the element via
  `ElementWireContext.for_kind("progress")` (`text_codec.py:61`–`:76`); reuse the
  existing `ctx.require_str`, `ctx.require_number`, `ctx.optional_str` /
  `optional_nullable_str` already used by the legacy `from_dict`
  (`progress.py:37`–`:42`). The encoder emits `{kind, id, fraction, label,
  tooltip}` and uses `strip_none` to omit absent optionals, matching the legacy
  wire shape (`text_codec.py:91`–`:103`).

### 2.4 The three-field difference from Text, and the tooltip bug it exposes

Progress has `{fraction, label, tooltip}`; Text has `{content, style, tooltip,
color}`. The only field needing a numeric validator is `fraction` (`_float_or_raise`);
`label` reuses the string validator; `tooltip` reuses the optional-string
validator. **Both** kinds carry `tooltip`, so the codec must handle it — and here
the migration must fix an existing inconsistency rather than copy it forward
(no "existing" excuse):

- The legacy `ProgressElement.to_dict` never emits `tooltip`
  (`progress.py:24`–`:32`) and `from_dict` never reads it
  (`progress.py:34`–`:42`), even though the field exists (`progress.py:22`).
- Today the field still round-trips only because the *generic* legacy paths fill
  the gap: `_element_to_dict` appends `tooltip` for non-ABC kinds
  (`elements/__init__.py:191`–`:192`) and `JsonElementFactory.element_from_dict`
  re-reads it and does `replace(elem, tooltip=...)` for non-ABC kinds
  (`element_factory.py:196`–`:205`).
- **Those two generic paths are SKIPPED for ABC kinds.** Text handles its own
  tooltip inside `JsonTextEncoder`/`JsonTextDecoder` (`text_codec.py:74`, `:100`)
  precisely because the generic append no longer runs once a kind is ABC. So
  `JsonProgressEncoder`/`JsonProgressDecoder` MUST own `tooltip` emission and
  parsing directly. Copying Text's codec faithfully gets this right; copying the
  *legacy progress* codec (which drops tooltip) would silently break tooltip
  round-trip the moment progress leaves the generic path. Flag: verify tooltip
  round-trips in a protocol test (§5).

---

## 3. The wiring change — flipping progress from SceneManager/legacy to HubDisplay/apply

Migrating progress touches the same set of registration points Text occupies.
Each is a place the code currently discriminates "ABC kinds" from "legacy
dataclass kinds." Progress must be added to the ABC side of each, and its legacy
registration removed in the same change (refactoring protocol: delete the old path
in the same commit — no dual path for one kind).

1. **`display/domain_pump.py:32` — `_ABC_TYPES`.** Add `ProgressElement`. Today
   `(TextElement, ButtonElement, DialogElement)`. This gates anonymous-id
   synthesis (`domain_pump.py:117`–`:137`): an ABC element cannot pass through
   `dataclasses.replace`, so an anonymous-id ABC element must raise rather than be
   silently `replace`d. Progress always carries an explicit id (unlike
   `separator`), so this addition is latent-safe — but it must be added for the
   ABC-set table of truth to be consistent (`element-migration-audit.md:82`–`:89`
   flags the analogous Checkbox omission).

2. **`protocol/element_factory.py` — decode dispatch (the JsonElementFactory).**
   - `_ABC_KINDS` frozenset (`element_factory.py:49`): add `"progress"`.
   - Add a `_progress_decoder: JsonProgressDecoder` field and construct it in
     `__new__` with the tier DI (mirror `text.py`'s decoder at
     `element_factory.py:90`–`:94`).
   - `decode()` (`element_factory.py:115`–`:129`): add
     `if kind == "progress": return self._progress_decoder.decode(raw)`.
   - `element_from_dict` narrowing (`element_factory.py:182`–`:189`,
     `:200`–`:204`): include `ProgressElement` in the isinstance unions so the
     boundary invariants recognize it as an ABC kind.

3. **`protocol/encoder_factory.py` — encode dispatch (the JsonEncoderFactory).**
   Add `if isinstance(elem, ProgressElement): return
   JsonProgressEncoder().encode(elem)` (mirror `encoder_factory.py:36`).

4. **`protocol/elements/__init__.py:185` — `_element_to_dict`.** Add
   `ProgressElement` to the isinstance tuple that routes through
   `_ENCODER_FACTORY` (currently `TextElement | ButtonElement | DialogElement`).
   This moves progress off the trailing generic-tooltip-append branch
   (`:188`–`:192`) and onto the per-kind encoder that now owns tooltip.

5. **Legacy codec removal.** The legacy progress registration goes through
   `build_element_codec()` → `BasicsRegistry().apply(codec.register)`
   (`elements/__init__.py:167`). Progress must be removed from `BasicsRegistry`
   (in `basics.py`) so the `ElementCodec` table no longer has a `progress` entry —
   otherwise there are two live decode/encode paths for one kind. The worker owns
   locating and removing that exact registration.

`ProgressElement` stays a member of the `Element` union
(`elements/__init__.py:152`) — it still satisfies the structural
`domain.element.Element` Protocol via its `to_dict`/`from_dict` delegators, exactly
as the ABC exemplars do (`element-migration-audit.md:46`–`:50`).

### 3.1 Mixed-scene coexistence stays intact

The `DomainPump.route` mixed-scene rule (`domain_pump.py:65`–`:81`) routes a
scene into the domain `Display` only when *every* element is a native kind;
`_NATIVE_KINDS` already includes progress via `_BASICS_KINDS`
(`display/server.py:110`). Migrating progress to an ABC subclass keeps it a member
of `_NATIVE_KINDS` (same class name, same `_BASICS_KINDS` tuple), so a scene of
migrated + not-yet-migrated *native* kinds still routes through `apply`, and a
scene containing any *non-native* kind still skips to SceneManager-only. Both
paths coexist during the migration — the design does not delete the legacy path
until Batch 7 (`element-migration-audit.md:318`–`:331`). A progress element in an
all-native scene is therefore dual-written: authoritative in the domain `Display`
*and* held by `SceneManager` (which the renderer still reads).

---

## 4. The introspection primitive

### 4.1 The problem it solves

`inspect_scene` today returns `{"scene_id", "elements": [element_to_dict(e) …]}`
by reading `SceneManager` (`query_dispatcher.py:98`–`:109`). That tells you an
element's *wire dict* but not (a) which render path the element object is on, nor
(b) its fully-resolved state when the wire omits defaulted fields (the encoder
drops `label` when `""`, `tooltip` when absent — `text_codec.py:100`,
`progress` similarly). A migration PR needs to assert, without looking at pixels:
"element `p1` is now on the ABC path, and its `fraction` reads back as `0.42`."
Neither fact is reliably available today. This primitive supplies both, and is
designed so every later migration reuses it unchanged.

### 4.2 Response shape (typed, per introspection-api.md)

`introspection-api.md:82`–`:98` mandates a stable, typed inspection surface that
verifies "what the real Hub/Display system did." The design adds a per-element
inspection record, carried alongside the existing `elements` array so existing
consumers are untouched (the current `elements` list stays byte-for-byte).

Extend `inspect_scene`'s result with an `element_paths` array — one record per
element, keyed by id:

```json
{
  "scene_id": "s1",
  "elements": [ { "kind": "progress", "id": "p1", "fraction": 0.42 } ],
  "element_paths": [
    {
      "id": "p1",
      "kind": "progress",
      "render_path": "abc",
      "hub_authoritative": true,
      "props": { "fraction": 0.42, "label": "Loading…", "tooltip": null }
    }
  ]
}
```

Field semantics:

- **`render_path`** — `Literal["abc", "legacy"]`. Computed as `"abc" if
  isinstance(elem, domain.element_abc.Element) else "legacy"`. This is the
  load-bearing flip signal: it reflects the element *object's* type in the
  authoritative store. For `progress` it is `"legacy"` before this PR and `"abc"`
  after. Boundary classification by isinstance against the ABC is appropriate here
  (a query-side boundary decision, not domain behavior).
- **`hub_authoritative`** — `bool`. True iff `ElementId(elem.id)` is present in
  `domain_display.snapshot(SceneId(scene_id)).element_ids` (`domain/display.py:187`).
  A second, independent signal that the pump routed the element into `HubDisplay`
  via `apply`, not just that its type is ABC. Caveat (§6 Q6): the pump skips
  mixed scenes containing a non-native kind, so `hub_authoritative` can be `False`
  while `render_path == "abc"` if the scene also holds an un-migrated non-native
  kind. The verification scene must be all-native so this field is deterministic.
- **`props`** — the element's fully-resolved state, *including* defaulted fields
  the wire omits. This is the "value reads back" surface. Resolution mechanism in
  §4.3.

The records serialize from a typed value class — `ElementInspection` (fields:
`id`, `kind`, `render_path`, `hub_authoritative`, `props`) composed into a
`SceneInspection` — with a `to_dict` method that produces the JSON above. These
live in a small dedicated module (types + behavior on the class, PY-OO-5), not as
loose dicts assembled in the handler.

### 4.3 How `props` is resolved — the extensible mechanism

`props` must report the full resolved state including defaults, so a test can
assert `label == ""` (default) as confidently as `fraction == 0.42`. The wire
dict omits defaults, so it is insufficient. The design resolves props via a small
runtime-checkable Protocol — the single-method-interface pattern (PY-DP-11) — that
migrated elements implement:

```python
@runtime_checkable
class Inspectable(Protocol):
    def resolved_props(self) -> Mapping[str, object]: ...
```

`ProgressElement.resolved_props()` returns `{"fraction": self._fraction,
"label": self._label, "tooltip": self._tooltip}` — every field, no omission. The
introspection handler does: `props = elem.resolved_props() if isinstance(elem,
Inspectable) else element_to_dict(elem)`. Legacy (not-yet-migrated) elements fall
back to their wire dict — acceptable because legacy elements are exactly the ones
a migration PR is *not* yet asserting against on the ABC path. As each kind
migrates it adds `resolved_props` alongside its setters, so the introspection
"scales with functionality" (each migration extends the verifiable surface by one
kind) without widening the Element ABC or adding an abstract method the four
existing exemplars would all have to implement in this PR. This is PY-TS-10
compliant (Protocol + isinstance, never `hasattr`).

Rationale for a Protocol over an ABC method: putting `resolved_props` on the ABC
as `@abstractmethod` would force image/separator/spinner/markdown/all inputs/all
composites to implement it before they migrate — scope the primitive can't carry.
The Protocol lets progress adopt it alone now, with the others adopting it kind by
kind. (§6 Q1 asks the operator to ratify this choice vs. reusing `to_dict` or
adding an ABC method.)

### 4.4 Where the enriched handler is registered

The enriched `inspect_scene` needs both stores in scope: `SceneManager` (for the
element list and existing `elements` array) and the domain `Display` (for
`hub_authoritative`). `QueryDispatcher` holds only `SceneManager`
(`query_dispatcher.py:24`, `:33`). `DisplayServer` holds both
(`display/server.py:163`, `:172`) and already registers cross-store handlers on
the dispatcher via `qd.register_handler(...)` for `screenshot`,
`get_display_info`, etc. (`display/server.py:271`–`:277`). The design registers
the enriched `inspect_scene` the same way — `qd.register_handler("inspect_scene",
self._query_inspect_scene_enriched)` — overriding the built-in. The built-in in
`QueryDispatcher` (`query_dispatcher.py:98`) stays as the no-domain-Display
fallback. This puts the cross-store logic where the domain `Display` is visible
and avoids widening `QueryDispatcher`'s constructor. (§6 Q2 asks the operator to
confirm this placement.)

### 4.5 How a test calls it — verifying progress without pixels

```python
resp = query("inspect_scene", {"scene_id": "s1"})
rec  = next(r for r in resp["element_paths"] if r["id"] == "p1")
assert rec["render_path"] == "abc"          # the flip
assert rec["hub_authoritative"] is True     # routed into HubDisplay
assert rec["props"]["fraction"] == 0.42     # value reads back
assert rec["props"]["label"] == "Loading…"
```

No screenshot, no ImGui, no eyeballing. The assertion is against live
Hub/Display state exactly as `introspection-api.md:13`–`:17` and `:76`–`:79`
intend.

---

## 5. Verification plan

### 5.1 Programmatic assertions (the primary gate)

Write the expected values down first, then drive the real entry point (the `show`
MCP tool / client API), then query `inspect_scene`:

1. **The flip.** `element_paths[p1].render_path == "abc"`. Capture the same
   assertion returning `"legacy"` on the parent commit (before migration) so the
   diff of behavior is explicit.
2. **Value reads back.** `props["fraction"] == 0.42`; `props["label"] ==
   "Loading…"`.
3. **Default reads back (boundary).** Show a progress with no label; assert
   `props["label"] == ""` (the wire omits it; `props` must still report it).
4. **HubDisplay routing.** `hub_authoritative is True` for an all-native scene.
5. **Patch through the ABC path.** Update the fraction via the real `update`
   tool; re-inspect; assert `props["fraction"]` reflects the new value AND
   `render_path` is still `"abc"`. This confirms the mutation went through
   `apply_patch`/`_set_fraction` (in-place), not `dataclasses.replace`.
6. **Protocol round-trip (unit).** `build → to_dict → from_dict → resolved_props`
   equal for all of `{fraction, label, tooltip}` — the tooltip round-trip
   specifically guards the §2.4 bug.
7. **Invalid input.** `_set_fraction("x")` raises `TypeError` (PY-EH-1 boundary
   validation), and a wire dict with a non-numeric `fraction` raises `ValueError`
   through `JsonProgressDecoder` / `ElementWireContext.require_number`.
8. **Missing-dependency / not-found.** `inspect_scene` on an unknown `scene_id`
   surfaces the `LookupError` as a `QueryResponse.error`
   (`query_dispatcher.py:68`–`:79`, `:104`–`:105`) — not a silent empty result.

### 5.2 The one manual confirmation that follows

After `make restart` (builds + restarts both luxd and the display), show a
progress bar through the real MCP tool and confirm by eye (or `screenshot`) that
the bar fills to the fraction and shows the overlay. This confirms the
programmatic result corresponds to correct pixels — manual testing confirms the
introspection, it does not replace it. Per the Definition of Done, ask the
operator to confirm the observed render matches the expected fraction/label.

### 5.3 make check / OO ratchet

`make check` (OO score, mypy, pyright, ruff, radon, pylint) must pass. The new
`progress.py` and `progress_codec.py` must meet the OO standard as written (they
are new-shape code, not "existing" code to preserve). Stage `.oo-baseline.json` +
`.oo-audit.jsonl` in the same commit.

---

## 6. Open questions / risks — the direction-check items

These are posed as concrete decisions with a recommendation each. No
implementation dispatches until they are ruled on.

**Q1 — Where does `resolved_props` live?** Recommend an `Inspectable` Protocol
(single-method, runtime-checkable) that migrated elements implement, resolved by
isinstance in the handler (§4.3). Alternatives: (a) reuse `to_dict` — rejected,
it omits defaults, defeating "default reads back"; (b) add `resolved_props` as an
`@abstractmethod` on the Element ABC — rejected for this PR, it forces all four
existing exemplars and every future kind to implement it before they migrate.
**Decision needed:** ratify the Protocol, or direct one of the alternatives.

**Q2 — Where is the enriched `inspect_scene` registered?** Recommend
`DisplayServer` registers it via `qd.register_handler("inspect_scene", …)`, the
existing pattern for cross-store handlers (§4.4), leaving `QueryDispatcher`'s
built-in as a fallback. Alternative: widen `QueryDispatcher.__new__` to take a
domain-Display snapshot callback. **Decision needed:** confirm the override
placement or direct the constructor-widening.

**Q3 — What does `render_path == "abc"` mean for a display-only leaf?** I am
asserting it means the element *object* is an ABC subclass, mutated via
`apply_patch`, encoded/decoded through the ABC codecs, and routed into
`HubDisplay` — but NOT that ImGui paint flows through `Element.render()` (that is
Batch 7; today paint still goes through `_dispatch_native` → `ProgressRenderer`,
§1.5). This is the single most load-bearing subtlety. **Decision needed:** confirm
this is the intended definition of "migrated" for a leaf, so the introspection's
`render_path` semantics are ratified before any assertion is written against them.

**Q4 — Should `fraction` be range-validated to [0, 1]?** The legacy decoder
(`ElementWireContext.require_number`, via `progress.py:39`) accepts any float and
the renderer does not clamp (`progress_renderer.py:23`; ImGui clamps visually).
Recommend **keep parity** — validate type only, no range clamp — to avoid a
behavior change riding along with a structural migration. **Decision needed:**
confirm no clamp, or direct that the ABC setter clamps/rejects out-of-range.

**Q5 — Confirm the live paint path claim.** I inferred from `_dispatch_native`
(`element_renderer.py:209`–`:234`) and the server comment "Renderer reads from
SceneManager during PR 1+2" (`display/server.py:166`–`:170`) that ABC elements —
including Text today — are painted by the legacy per-kind renderer, not by
`Element.render()`. I did not trace the full frame loop end to end. **Risk:** if
Text is in fact painted via `Element.render()` somewhere I did not read, §1.5 and
Q3 change. Recommend the implementation mission's first step verify the paint path
for the existing Text element before copying the pattern. **Not a blocker, but a
check to schedule.**

**Q6 — `hub_authoritative` and mixed scenes.** The pump skips any scene
containing a non-native kind (`domain_pump.py:72`), so an ABC-typed progress in a
mixed scene would report `render_path == "abc"` but `hub_authoritative == False`.
That is informative, not wrong — but a naive test could over-assert. Recommend the
verification scene contain only native/migrated kinds so `hub_authoritative` is
deterministic, and document the mixed-scene caveat next to the field. **Decision
needed:** none if the recommendation is accepted; flag if the operator wants
`hub_authoritative` to mean something stricter.

**Q7 — The tooltip inconsistency (§2.4).** The legacy `ProgressElement` codec
drops `tooltip`; it survives today only via generic paths that ABC kinds skip. The
migration must make `JsonProgressEncoder`/`Decoder` own tooltip directly (as Text
does), and §5.1 item 6 guards it. This is a fix-in-place, not a deferral (no
"existing" excuse). **Decision needed:** none — flagged so the operator knows a
latent asymmetry is being corrected as part of the migration, not carried forward.

---

## 7. Report status

Design + verification plan only. No production code, tests, or introspection
implementation written. Saved to
`docs/architecture/migration/progress-element-design.md`.
