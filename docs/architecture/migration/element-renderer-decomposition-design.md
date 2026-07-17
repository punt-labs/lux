# Decomposing `element_renderer.py` — end the per-kind accretion

**Status:** design, awaiting operator ratification.
**Bead:** lux-m4r8.
**Kind of change:** display-tier refactor. Sequential rendering dispatch — no
concurrency, no lock, no state machine, so no z-spec (a scene/roundtrip test is
the merge gate; see §11).
**Grounding docs:** `target.md` (Hub authoritative, render calls stay
Display-local), `element-contract.md` (the ABC render template), `migration/README.md`
(DES-041 fork-don't-mix, DES-042 transitional rendering), DES-051 (the one-registry
pattern this design follows).

## 1. Problem

`display/element_renderer.py` is 467 non-blank lines against the 300-line
PY-OO-2 target — the worst-offending module after `server.py`. Worse than its
size is its *growth rate*. Every atomic-kind ABC migration bolts more onto it,
and each addition has had to be offset by trimming three lines elsewhere so the
OO ratchet does not record the over-target debt going up. DES-052 states the
rule plainly: combo, radio, and selectable were each "kept in
`element_renderer._NATIVE_DISPATCH` exactly as the checkbox exemplar does." The
next batches — the Batch 1 display leaves, then the composites, plot, draw,
table — all want to touch this file, and the offset slack is gone.

The file is not merely large; it is the hand-wired assembly point for a per-kind
dispatch table that *duplicates a table that already exists elsewhere*. Migrating
one kind today edits this file in five to seven places:

- an import from `renderers` (`element_renderer.py:14`)
- a `protocol.elements.<kind>` type import (`:36`)
- a `_<kind>_renderer` field declaration (`:79`)
- a construction line in `__new__` (`:127`)
- a row in `_NATIVE_DISPATCH` (`:149`)
- sometimes a row in `_WIDGET_STATE_RENDERERS` (`:168`)
- often a `@property` accessor the ImGui adapter reads back through (`:182`)

…and *also* a row in `imgui/factory.py`'s `_DISPATCH` (`factory.py:67`), and a
spec in `abc_kind_table.py`. Three god-tables carry the same fact — *which kind
paints via which renderer* — and they drift. The checkbox half-migration
regression recorded in `tests/CLAUDE.md` is exactly a "these copies drifted"
failure. This is the same disease DES-051 diagnosed in `element_factory.py`, one
layer down.

## 2. What the file holds today

Four responsibilities are tangled in one class (`ElementRenderer`), with line
spans:

- **(A) Migrated-kind native leaf dispatch** — `_NATIVE_DISPATCH`
  (`:149`–`:165`), the 15 `_<kind>_renderer` fields (`:79`–`:94`), their
  construction (`:127`–`:142`), the 11 accessor properties (`:182`–`:244`),
  `_WIDGET_STATE_RENDERERS` (`:168`–`:174`), and `_dispatch_native`
  (`:315`–`:325`). ~180 lines. This is a *duplicate* of `factory._DISPATCH`.
- **(B) Legacy string dispatch** — `_RENDERERS` (`:99`–`:110`), the
  `render_element` fallback (`:278`–`:288`), and the thin container delegators
  (`:329`–`:343`). ~40 lines. Shrinks as kinds migrate.
- **(C) Inline legacy renderer bodies** — full ImGui paint code that never got
  extracted the way `table`/`draw`/`container` did: `_render_tree` +
  `_render_tree_node` + `_emit_node_click` (`:347`–`:410`, ~66 lines);
  `_render_plot` + `_plot_series` (`:424`–`:458`, ~37 lines); `_render_modal`
  (`:465`–`:512`, ~53 lines). ~156 lines of paint that belong in dedicated
  renderer classes.
- **(D) Cross-cutting plumbing** — `apply_tooltip` (`:294`–`:313`),
  `widget_state`/`current_scene_id`/`imgui_renderer_factory` properties and
  setters (`:247`–`:274`), `element_kind_count` (`:176`–`:179`).

Responsibility C is pure, mechanical debt: it was simply never extracted.
Responsibility A is the accretion engine — it grows on every migration and it
duplicates the factory.

## 3. Root cause — one fact, three code homes

The Display already has a registry that maps an element to its renderer: the
`ImGuiRendererFactory` (`factory.py:57`). Its `_DISPATCH` tuple (`factory.py:67`)
is *the* kind→adapter table, and `Element.render()` — the ABC template — resolves
through it. `_NATIVE_DISPATCH` in `element_renderer.py` is a second copy of the
same mapping, reached by a *different* path (the legacy `render_element` walk).
Both ultimately call the same stateless per-kind renderer: the ABC path via
`adapter.paint()` → `factory.element_renderer.<kind>_renderer.render(elem)`
(e.g. `imgui/slider.py:38`), the native path via
`_dispatch_native` → `self._<kind>_renderer.render(elem)`.

So the two tables converge on one renderer through two hand-maintained routes.
The fix is not to relocate `_NATIVE_DISPATCH` — it is to *delete* it and route
its one caller through the factory that already holds the mapping. This is
DES-051's lesson: kill the duplicate at the root, do not split the god-module and
keep the copies.

## 4. The carve

Three moves, aligned with the migration direction so the module shrinks as kinds
cross rather than growing.

### 4.1 Extract the inline legacy renderer bodies (responsibility C)

Follow the `ContainerRenderer` model verbatim (`container_renderer.py:37` — a
`@final` class in its own module, injected state, a `render_child` callback for
recursion, never imports the dispatch table). Create:

| New module | Class | Injected | Replaces |
|---|---|---|---|
| `display/renderers/tree_renderer.py` | `TreeRenderer` | `emit_event` | `_render_tree`, `_render_tree_node`, `_emit_node_click` |
| `display/renderers/plot_renderer.py` | `PlotRenderer` | — | `_render_plot`, `_plot_series` |
| `display/renderers/modal_renderer.py` | `ModalRenderer` | `widget_state`, `emit_event`, `render_child` | `_render_modal` |

Each owns its paint behavior (PY-OO-5) and is independently testable — `plot`
and `tree` render deterministically from a wire element; `modal` drives its
open/dismiss latch through injected `WidgetState`, testable without a live
display. The legacy `_RENDERERS` delegators in `element_renderer.py` shrink to
one-line calls into these classes (or the `_RENDERERS` row points straight at the
class, see §4.3). ~156 lines leave the god-module as behaviour-preserving
paydown.

These are legacy kinds. Extracting them into the renderer-class shape is not
wasted work: it is the exact shape their eventual ABC migration needs (the audit,
§4 "Where the legacy render logic moves — Nowhere new"). When `plot` migrates,
its adapter paints *through the already-extracted `PlotRenderer`*, and the
`element_renderer.py` delegator is deleted — a net line loss (§6).

### 4.2 Route migrated kinds through the factory; retire `_NATIVE_DISPATCH` (responsibility A)

`render_element` (`:278`) is the legacy container's child-dispatch hook and the
top-level legacy walk (`server.py:1447`). Its ABC branch should resolve through
the factory, exactly as `_render_dialog` already does for the transitional dialog
(`:528` — `renderer = self._imgui_renderer_factory(elem); renderer.begin()…`).
Generalising that one proven method retires the whole native-dispatch surface:

```python
def render_element(self, elem: Element) -> None:
    if self._imgui_renderer_factory.handles(elem):
        # DES-042 transitional + ABC path: one route, via the adapter template.
        elem_adapter = self._imgui_renderer_factory(elem)
        opened = elem_adapter.begin()
        try:
            if opened:
                elem_adapter.paint()
        finally:
            elem_adapter.end(opened=opened)
    else:
        method_name = self._RENDERERS.get(elem.kind)   # legacy, shrinking
        ...
```

`handles(elem) -> bool` is a new boolean predicate on the factory (PY-EH-4 —
normal branch, not exception control flow; the existing `__call__` keeps raising
for a genuinely-unknown type, which is a bug). With this, `_NATIVE_DISPATCH`,
`_dispatch_native`, and — for adapter-backed kinds — the per-kind fields,
construction, and accessors all disappear from `element_renderer.py`.

**Ownership of the stateless renderers moves off `ElementRenderer`.** The
per-kind renderers are pure functions of `(elem, widget_state)` — `SliderRenderer`
builds a fresh `ContinuousEditArbiter` every frame and keeps *no* buffer of its
own; the buffer lives in `WidgetState` keyed by element id
(`slider_renderer.py:62`–`:80`). So they need not be long-lived singletons that
`ElementRenderer` re-threads. **Recommended:** each ImGui adapter constructs its
stateless renderer per paint with `widget_state=self._factory.widget_state`, and
calls tooltip via the factory (see below). Per-frame construction of a tiny
object is behaviour-preserving and deletes `_WIDGET_STATE_RENDERERS` and both
re-thread loops (`element_renderer.py:250`–`:257` and `factory.py:105`–`:113`)
outright. The worker owns this adapter-internals decision; the alternative —
the factory owns the stateless renderers and re-threads them — is also valid but
grows the factory and keeps a re-thread loop.

**`apply_tooltip` moves onto the factory** (or a small `TooltipPainter` value
class). Today every adapter reaches `factory.element_renderer.apply_tooltip`
(`imgui/slider.py:42`). Once tooltip and the stateless renderers no longer live
on `ElementRenderer`, adapters stop reaching back through it: the
`factory._element_renderer` back-reference (`factory.py:63`, `:97`, `:126`) is
deleted and the `ElementRenderer ⇄ factory` cycle is broken (PL-CU-2).

### 4.3 The residual native table empties itself

Four display-only leaves are in `_NATIVE_DISPATCH` today but are *not* yet ABC
subclasses and have no adapter: `image`, `separator`, `spinner`, `markdown`
(audit §3, rows 5/6/8/9). Two options, both acceptable:

- **(recommended, minimal)** Keep a 4-entry residual table for exactly these,
  down from 15. It cannot grow — every new kind lands on the ABC/factory path —
  and it empties entirely when Batch 1 migrates those four.
- **(cleaner, more scope)** Give the four trivial leaf adapters now (each ~15
  lines, `begin`→`True`/`paint`→stateless-renderer+tooltip/`end`→no-op, the
  `imgui/selectable.py` shape) and register them in `factory._DISPATCH`. The
  factory dispatches on element *type*; ABC-ness is not required. This retires
  `_NATIVE_DISPATCH` completely in one step, at the cost of touching four kinds'
  render path ahead of their full migration.

Either way the table stops being an accretion vector: it only ever loses rows.

## 5. Module map (target)

```text
display/
  element_renderer.py        # THIN: render_element (factory-route + legacy
                             # string fallback), plumbing, element_kind_count.
                             # ~150 lines. No per-kind surface.
  renderers/
    leaf_widget_renderer.py  # NEW: LeafWidgetRenderer runtime_checkable Protocol
    tree_renderer.py         # NEW: TreeRenderer
    plot_renderer.py         # NEW: PlotRenderer
    modal_renderer.py        # NEW: ModalRenderer
    container_renderer.py     # (model followed by the three above)
    <kind>_renderer.py        # unchanged stateless renderers
    imgui/
      factory.py             # gains handles(); optionally hosts apply_tooltip;
                             # loses the _element_renderer back-reference
      <kind>.py              # adapters pull stateless renderer from factory
```

`LeafWidgetRenderer` is a `runtime_checkable` Protocol with a single method
`render(self, elem) -> None` (families share via Protocol, **not** a base class).
`TreeRenderer`, `PlotRenderer`, `ModalRenderer`, and the existing stateless
renderers satisfy it structurally; tests assert `isinstance(x, LeafWidgetRenderer)`
for the family contract. No `BaseRenderer` is introduced.

## 6. Shrink-as-migrate — the mechanism, concretely

**Today**, migrating `plot` (a legacy string-dispatch kind) touches
`element_renderer.py` in the growth direction: it would add a field, a
construction line, a `_NATIVE_DISPATCH` row, and an accessor — *plus* a
`factory._DISPATCH` row and an `abc_kind_table` spec. The god-module grows.

**After this decomposition**, migrating `plot`:

1. add `imgui/plot.py` — an adapter that paints through the *already-extracted*
   `PlotRenderer` (unchanged from §4.1);
2. add **one** row to `factory._DISPATCH`;
3. add **one** spec to `abc_kind_table.py` (the DES-051 single source);
4. **delete** the `"plot": "_render_plot"` row from `_RENDERERS` **and delete**
   the `_render_plot` delegator from `element_renderer.py`.

Net effect on `element_renderer.py`: **negative lines**. The per-kind work is now
additive to two registries (`factory._DISPATCH`, `abc_kind_table`) and
subtractive from the god-module. `element_renderer.py` is never edited to *add* a
kind again. That is the property the mission requires: the accretion ends, and
the module shrinks as the fork completes. When the last legacy kind crosses,
`_RENDERERS`, `render_element`'s legacy branch, and the container delegators all
delete (audit Batch 7), leaving `render_element` as a pure factory route.

## 7. DES-042 preservation

DES-042 requires that a migrated **leaf** nested in a still-legacy container keep
rendering — via the retained legacy per-kind renderer — until the fork completes.
This design *strengthens* that guarantee. Today the transitional path
(`_dispatch_native`) and the ABC path (`Element.render()` → factory adapter) are
two tables that must agree; the checkbox regression is what happens when they do
not. After §4.2, both routes resolve through the **same** factory adapter, so a
leaf-in-legacy-container paints through the identical `begin/paint/end` the
top-level ABC path uses — byte-identical pixels, by construction, with the
divergence risk removed. This is the exact generalisation of `_render_dialog`,
which already renders a transitional dialog through the factory
(`element_renderer.py:516`).

Fork-don't-mix (DES-041) means an ABC *container* is never nested in a legacy
one, so `render_element`'s ABC branch only ever paints leaves (and the
transitional dialog, a self-contained composite that recurses its own children).
No regression to the 15 migrated kinds: PR2's merge gate is a render-through of
all 15 plus a leaf-in-legacy-container case, introspected and operator-confirmed
(§11).

## 8. Legacy path disposition

The `_RENDERERS` string dispatch **stays** in `element_renderer.py`, minus the
rows whose bodies were extracted in §4.1 (which now point at the extracted
classes or one-line delegators). It is the simplest correct fallback for the
~9 unmigrated kinds and it self-deletes as each migrates (§6). No elaborate
legacy bridging is built: the legacy walk hits `_RENDERERS.get(kind)` and, on a
miss, paints `[unsupported element: <kind>]` exactly as today (`:288`). This
honours the "legacy = simple fallbacks, focus on finishing migration" rule.

## 9. Rejected alternatives

- **Per-family split of the renderers** (`basics_renderers.py`,
  `input_renderers.py`, …). Clears the 300-line bar by *relocating* mass, but
  `element_renderer.py` keeps hand-maintaining `_NATIVE_DISPATCH` and the
  god-dispatch still grows one row per migration. This is precisely the "split
  `element_factory.py` into two files" option DES-051 rejected: symptom, not
  disease. **Rejected.**
- **A brand-new `RenderKindRegistry`** mirroring `abc_kind_table.py`, holding
  per-kind render specs. The Display *already has* this registry — the
  `ImGuiRendererFactory`. Building a second one beside it re-creates the
  many-copies drift the mission warns against instead of curing it. The correct
  move is to make the existing factory the single source and delete the
  duplicate. **Rejected** (its spirit — one additive source of truth — is
  adopted via the factory).
- **Leave the inline legacy bodies (C) in place, only retire `_NATIVE_DISPATCH`.**
  Retires the accretion vector but leaves ~156 lines of un-extracted paint, so
  `element_renderer.py` stays over 300 and `tree`/`plot`/`modal` have no testable
  render unit. Half the paydown for most of the risk. **Rejected** — do both.
- **Keep the two tables, add a cross-check to detect drift.** Makes drift
  fail-loud but keeps the maintenance-in-two-places cost on every migration. A
  cross-check is worth having as *hardening* (§10, PR3) but is not a substitute
  for deleting the duplicate. **Rejected as the primary fix.**

## 10. Write-set and the ratchet story

**Create:** `renderers/tree_renderer.py`, `renderers/plot_renderer.py`,
`renderers/modal_renderer.py`, `renderers/leaf_widget_renderer.py`
(each ≤300 lines, ≤3 classes). Optionally the four leaf adapters (§4.3, cleaner
option) and a `TooltipPainter`.

**Rewrite:** `element_renderer.py` (retire A and C; thin `render_element`);
`imgui/factory.py` (add `handles`; optionally host `apply_tooltip`; drop the
`_element_renderer` back-reference); the ImGui adapters that read
`factory.element_renderer.<kind>_renderer` (repoint to per-call construction from
`factory.widget_state`); `renderers/__init__.py` / `imgui/__init__.py` exports;
`server.py` if `element_kind_count` wiring (`server.py:758`) moves.

**Delete:** `_NATIVE_DISPATCH`, `_dispatch_native`, the per-kind fields /
construction / accessors, `_WIDGET_STATE_RENDERERS`, and the three extracted
render bodies from `element_renderer.py`; `_render_dialog` too **iff** the worker
verifies the renderer factory is bound on ABC leaves nested in legacy containers
(if so, the ABC branch can be `elem.render()` and `_render_dialog` folds in; if
not, keep the explicit factory route). This binding check is the one open
verification the worker must resolve before choosing between `elem.render()` and
the explicit `factory(elem).begin/paint/end` form.

**Ratchet — genuine paydown, not relocation.** `element_renderer.py`'s
`module_size` drops from 467 toward ~150 because A and C move to focused modules
that are each independently ≤300 and testable — this is a real reduction of the
single worst file, **not** a `--rebaseline` absorption of growth (which the
project forbids on an over-target file). Each new renderer class raises
`method_ratio` and `class_to_func_ratio` in the `display` package. Run
`make update-oo` and stage `.oo-baseline.json` + `.oo-audit.jsonl` in the **same
commit** as each source change.

## 11. PR granularity

Split by rollback coherence into a **sequence of two** (a third optional),
each keeping `make check` green and all 15 migrated kinds rendering:

- **PR1 — extract the inline legacy renderers (C).** `TreeRenderer`,
  `PlotRenderer`, `ModalRenderer`, the `LeafWidgetRenderer` Protocol; `_RENDERERS`
  delegators repoint. No ABC-path change, behaviour-preserving. ~156 lines out of
  `element_renderer.py`, big `module_size` win, lowest risk. Merge gate: scene
  tests rendering a tree, a plot with each series type, and a modal open/dismiss
  cycle; all kinds render identically.
- **PR2 — unify the transitional/ABC route on the factory (A).** Add
  `factory.handles`; route `render_element`'s ABC branch through the adapter;
  retire `_NATIVE_DISPATCH`; move stateless-renderer access to per-call from the
  factory; move `apply_tooltip` to the factory; drop the back-reference; empty or
  reduce the residual table (§4.3). Behaviour-sensitive. Merge gate: render every
  one of the 15 migrated kinds **and** a migrated leaf inside a legacy container,
  captured via `inspect_scene` / `list_recent_events` and operator-confirmed
  against expected output written beforehand (Definition of Done item 4).
- **PR3 (optional hardening) — DES-051-style drift guard.** A fail-loud
  import-time cross-check that `factory._DISPATCH` covers exactly the ABC
  registry's `abc_types`, so a future migration that adds a codec spec but forgets
  the adapter fails at process start, not as a silent `[unsupported element]`.
  Plus a DES ADR entry recording this decomposition.

PR1 and PR2 are independently revertable and independently valuable; PR3 folds
into PR2 or stands alone. This is a `standard`-pipeline change (it touches the
render path); worker/evaluator per the Lux pairing table is `rmh` worker / `gvr`
evaluator (Python implementation, rendering).

## 12. OO rules in scope (cited, with one BEFORE/AFTER)

- **PY-OO-2 (≤300 lines, ≤3 classes/module).** The whole point.
  `element_renderer.py` 467 → ~150; each new module ≤300, one class each.
- **PY-OO-5 (data + behaviour on the class).** Render bodies that read an
  element's fields are behaviour that belongs on a renderer class, not piled onto
  a god-dispatcher.

  BEFORE (`element_renderer.py:424`):

  ```python
  class ElementRenderer:
      def _render_plot(self, elem: Element) -> None:
          plt: Any = elem
          if implot.begin_plot(...):
              for series in plt.series:
                  self._plot_series(series)
      @staticmethod
      def _plot_series(series: dict[str, Any]) -> None:
          s_type: str = series.get("type", "line")   # str-with-implicit-values
          if s_type == "line": ...
  ```

  AFTER (`renderers/plot_renderer.py`):

  ```python
  @final
  class PlotRenderer:
      def render(self, elem: PlotElement) -> None: ...
      @staticmethod
      def _plot_series(series: PlotSeries) -> None: ...   # owns plot behaviour
  ```

- **Families share via Protocol, not a base class.** BEFORE: `_dispatch_native`
  duck-types via `getattr(self, renderer_attr).render(elem)` (`:323`) — no
  declared contract. AFTER: a `runtime_checkable LeafWidgetRenderer` Protocol
  (`render(self, elem) -> None`) that every renderer satisfies structurally;
  `isinstance` asserts the family contract in tests. No `BaseRenderer`.
- **PY-IC-1 (composition over inheritance).** The three extracted renderers
  compose injected collaborators (`emit_event`, `widget_state`, `render_child`),
  following `ContainerRenderer` (`container_renderer.py:56`) — no inheritance.
- **Literal over str-with-comment.** `PlotRenderer` is the right home to replace
  `s_type: str` with `Literal["line", "scatter", "bar"]` on a typed `PlotSeries`
  value class (the draw-command family is the model; audit §4). Full plot typing
  is the `plot` migration, but the extraction opens the door.
- **Reduce `| None`.** `render_element` no longer needs
  `_current_scene_id: str | None` threaded for native dispatch; scene id flows to
  the renderers that need it (`table`, `modal`) via injection, tightening the
  Optional surface.

## 13. Open verification for the worker

1. **Factory binding on legacy-nested ABC leaves.** Decides whether the ABC
   branch is `elem.render()` (if the Display's post-receive rebind binds every
   ABC element in the tree) or the explicit `factory(elem).begin/paint/end`
   (if not). `_render_dialog` uses the explicit form today, implying the safe
   default is explicit; confirm before folding `_render_dialog` in.
2. **Per-call vs factory-owned stateless renderers.** Recommended: per-call from
   `factory.widget_state`. Confirm no stateless renderer holds frame-spanning
   state beyond `WidgetState` (verified for `slider`; check `input_text`,
   `input_number`, `color_picker`).
