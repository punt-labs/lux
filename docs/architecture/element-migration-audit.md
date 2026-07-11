# Element Migration Audit — Distributed Element-ABC / Hub-Display

> **Superseded in part by [DES-041](../../DESIGN.md).** The migration
> **strategy and sequencing** in this document — "incremental crossing,
> big-bang deletion," mixed-scene coexistence, and the lowest-risk-first
> "Batch 0–7" order — are replaced by DES-041: **fork, don't mix; duplicate on
> need (new class gets the canonical name); order by testability (a container +
> primitives first, complex widgets last).** The **per-element map** below
> (which kinds are migrated, what "migrated" means per class, the display-only
> vs interactive vs composite split) still holds; read the ordering and
> coexistence recommendations as historical.

**Status:** read-only audit and proposed epic. No code changes.
**Scope:** the 25 element kinds in `src/punt_lux/protocol/elements/` and their
migration from the legacy `SceneManager` + dual-write path onto the Element ABC
(`src/punt_lux/domain/element_abc.py`) and the `HubDisplay`/`apply` path.
**Ground truth:** `docs/architecture/target/{target,ui-model,topology,element-contract,introspection-api}.md`
and the code cited inline. Where a document disagrees with `target.md`, the
target is authoritative.

This audit is a design and sequencing map, not a line-by-line implementation
plan. It identifies what is migrated, what "migrated" means per class, a
defensible order, effort shape, the open design decisions that need operator
ratification, and a proposed epic + child-bead structure.

## 1. What "the ABC contract" actually is

The behavioral contract every migrated kind must satisfy is defined by
`domain.element_abc.Element` (`element_abc.py:49`). Concretely:

- **`id`** — abstract read-only property (`element_abc.py:100`). The only
  abstract member; everything else is inherited.
- **`render()`** — template method, never overridden (`element_abc.py:105`).
  It calls `renderer_factory(self)` and either `renderer.render()` for a leaf
  or `begin()/child.render()/end()` for a composite.
- **`_children()`** — hook returning `()` by default; composites override it
  (`element_abc.py:119`). This is the single structural extension point.
- **`apply_patch()`** — walks the patch dict and dispatches each key to a
  `_set_<key>` setter (`element_abc.py:124`). Replaces the frozen-dataclass
  `replace(...)` path for ABC kinds.
- **Handler registry** — `add_handler` / `remove_handler` / `fire`
  (`element_abc.py:151`, `:160`, `:177`), keyed by `Event` subclass, snapshot
  dispatch, fan-out-safe.
- **`wrap_handlers_for_remote()`** — the D21 two-tier seam
  (`element_abc.py:213`). It recurses through `_children()` and, for the kinds
  it knows how to wrap (`ButtonElement` on `ButtonClicked`, `CheckboxElement`
  on `ValueChanged`), replaces the handler bucket with one `RemoteDispatchGroup`.
- **Observer surface** — `add_observer`, `removed`, `mark_removed`
  (`element_abc.py:284`, `:292`, `:297`). The single removal mechanism for
  agent `RemoveElement`, component self-dismiss, and disconnect.
- **Wire pickling** — `__reduce__` / `__setstate__` (`element_abc.py:78`,
  `:94`). Reconstructs via `object.__new__` (bypassing the keyword-only
  `__new__`), drops `_observers` (Hub-side closures that can't cross the wire),
  preserves handlers so the Display can wrap them.

The `domain.element.Element` **Protocol** (structural, `to_dict`/`from_dict`/
`kind`/`id`) is a *separate* contract that the frozen wire dataclasses still
satisfy. Both names coexist. A migrated kind satisfies **both**: it subclasses
the ABC *and* keeps `to_dict`/`from_dict` delegators so the structural Protocol
still holds (see `text.py:160`, `checkbox.py:144`).

## 2. Migration state — the four exemplars

Four kinds are ABC subclasses today: `TextElement` (`text.py:47`),
`ButtonElement` (`button.py:52`), `CheckboxElement` (`checkbox.py:41`),
`DialogElement` (`dialog.py:131`). They demonstrate three of the four shapes a
migration can take:

- **Display-only leaf** — `TextElement`. No handlers, `_children()` inherits the
  empty default, setters cover the patch fields. This is the template for every
  basic display element.
- **Interactive leaf** — `ButtonElement` (`ButtonClicked`) and `CheckboxElement`
  (`ValueChanged`). Same as display-only *plus* the kind is a branch inside
  `wrap_handlers_for_remote` (`element_abc.py:231`, `:248`) and carries an
  `action`/value interaction.
- **Composite with a private model** — `DialogElement`. Owns a `DialogModel`
  (`dialog.py:50`), overrides `_children()` (`dialog.py:215`), installs children
  via a decoder seam (`dialog.py:221`), and binds `model.on_dismiss` to its own
  `mark_removed`. Its child Buttons are the interactive controllers.

Two structural facts constrain the wrap seam. `wrap_handlers_for_remote`
enumerates the wrappable kinds **by isinstance inside the ABC**
(`element_abc.py:231`–`:264`). Every new interactive kind must either be added
to that method or the method must be refactored so each element declares its own
interaction — see Decision (e).

### 2a. Two discrepancies to verify before migrating more kinds

These are inconsistencies in the current shipped code, not future work. Per the
"no existing excuse" rule they belong to whoever next touches these files.

- **`domain_pump._ABC_TYPES` omits `CheckboxElement`** (`domain_pump.py:32`).
  The tuple is `(TextElement, ButtonElement, DialogElement)`. `element-contract.md`'s
  "Migration status" section states checkbox is a shipped ABC element, and it *is* an ABC subclass
  (`checkbox.py:41`). The tuple gates anonymous-id synthesis (`domain_pump.py:128`):
  an anonymous-id Checkbox would fall through to `dataclasses.replace` on an ABC
  instance instead of raising the intended `ValueError`. In practice checkboxes
  always carry an explicit id, so this is latent, not active — but it is a real
  inconsistency and any table-of-truth for the ABC set must reconcile it.
- **`_element_to_dict` encode special-case omits Checkbox** (`__init__.py:185`).
  The encode dispatcher routes `TextElement | ButtonElement | DialogElement`
  through `JsonEncoderFactory` and everything else through the codec table with a
  trailing tooltip append (`__init__.py:191`). Checkbox reaches encode through
  the codec table (registered at `inputs.py:48`) and its own `to_dict`
  (`checkbox.py:144`). Confirm the tooltip is emitted exactly once for checkbox
  and not double-appended before adding more ABC kinds to either branch.

## 3. Per-element migration table

Interactivity is the load-bearing axis. **INTERACTIVE** = fires events / carries
handlers → needs the full `wrap_handlers_for_remote` seam. **DISPLAY-ONLY** = no
app-facing handlers → needs an ABC with `id`/`render`/`_children` + the
`HubDisplay`/`apply` move, but *not* handler-wrapping.

The 25 kinds are the `Element` union at `__init__.py:130`.

| # | Kind | Class (file) | Path today | Interactive? | Special complexity |
|---|------|--------------|-----------|--------------|--------------------|
| 1 | `text` | `TextElement` (`text.py:47`) | **ABC** ✓ | Display-only | — (leaf exemplar) |
| 2 | `button` | `ButtonElement` (`button.py:52`) | **ABC** ✓ | **Interactive** (`ButtonClicked`) | wrap seam `element_abc.py:231` |
| 3 | `checkbox` | `CheckboxElement` (`checkbox.py:41`) | **ABC** ✓ (see 2a) | **Interactive** (`ValueChanged`) | wrap seam `element_abc.py:248` |
| 4 | `dialog` | `DialogElement` (`dialog.py:131`) | **ABC** ✓ | **Interactive** (composite) | private model + children (`dialog.py:50`,`:215`) |
| 5 | `image` | `ImageElement` (`image.py`) | Legacy dataclass | Display-only | image texture (`texture_cache`) |
| 6 | `separator` | `SeparatorElement` (`separator.py:15`) | Legacy dataclass | Display-only | anonymous id (`""`) → id-synthesis path |
| 7 | `progress` | `ProgressElement` (`progress.py`) | Legacy dataclass | Display-only | — |
| 8 | `spinner` | `SpinnerElement` (`spinner.py`) | Legacy dataclass | Display-only | — |
| 9 | `markdown` | `MarkdownElement` (`markdown.py`) | Legacy dataclass | Display-only | — |
| 10 | `slider` | `SliderElement` (`slider.py:15`) | Legacy dataclass | **Interactive** (`value`) | `widget_value()` → WidgetState mirror |
| 11 | `combo` | `ComboElement` (`combo.py`) | Legacy dataclass | **Interactive** (`value`) | `widget_value()` |
| 12 | `input_text` | `InputTextElement` (`input_text.py`) | Legacy dataclass | **Interactive** (`value`) | `widget_value()` |
| 13 | `input_number` | `InputNumberElement` (`input_number.py`) | Legacy dataclass | **Interactive** (`value`) | `widget_value()` |
| 14 | `radio` | `RadioElement` (`radio.py`) | Legacy dataclass | **Interactive** (`value`) | `widget_value()` |
| 15 | `color_picker` | `ColorPickerElement` (`color_picker.py`) | Legacy dataclass | **Interactive** (`value`) | WidgetState seeded as `ImVec4`; excluded from `_widget_value` (`manager.py:81`) |
| 16 | `selectable` | `SelectableElement` (`selectable.py:15`) | Legacy dataclass | **Interactive** (`selected`) | `widget_value()` |
| 17 | `group` | `GroupElement` (`layout.py:27`) | Legacy dataclass | Display-only composite | children + `pages` + `page_source` combo linkage |
| 18 | `tab_bar` | `TabBarElement` (`layout.py:48`) | Legacy dataclass | Display-only composite | children live in `tabs: list[dict]`; active-tab view state |
| 19 | `collapsing_header` | `CollapsingHeaderElement` (`layout.py:58`) | Legacy dataclass | Display-only composite | children; open/closed view state |
| 20 | `window` | `WindowElement` (`layout.py:70`) | Legacy dataclass | Display-only composite | drag/resize position; `_dirty_windows` (`manager.py:481`) |
| 21 | `tree` | `TreeElement` (`layout.py:91`) | Legacy dataclass | Display-only composite | `nodes: list[dict]` (not Element children); expansion view state |
| 22 | `modal` | `ModalElement` (`layout.py:113`) | Legacy dataclass | **Interactive** composite | emits `"closed"`; children |
| 23 | `table` | `TableElement` (`table.py:74`) | Legacy dataclass | Display-only *with built-in behavior* | filters/search/selection view state (`table.py:18`,`:49`) |
| 24 | `plot` | `PlotElement` (`plot_element.py:17`) | Legacy dataclass | Display-only | `series: list[dict]` — untyped (`plot_element.py:27`) |
| 25 | `draw` | `DrawElement` (`graphics.py:27`) | Legacy dataclass | Display-only | typed draw-command family (curve/line/shape/text) |

Summary: **as of this audit, 4 migrated, 21 legacy.** Since then `group`
(the first container, PR #240) and `progress` (the first display-only
primitive, PR #241) have crossed — **6 migrated, 19 legacy**. The authoritative
live status is [`migration/README.md`](migration/README.md) §"Where we are";
this table is the original per-element analysis. Of the 19 legacy: **~8
interactive** (slider, combo, input_text, input_number, radio, color_picker,
selectable, modal, and — structurally — the table/plot only if selection
becomes Hub-authoritative), **~11 display-only** (image, separator, spinner,
markdown, tab_bar, collapsing_header, window, tree, plot, draw), with table
sitting on the boundary.

## 4. What "migrated" means per class

The concrete ABC contract each shape must satisfy, and where the legacy render
logic moves.

### Display-only leaf (image, separator, progress, spinner, markdown, plot)

- Subclass `Element` (`element_abc.py:49`) with keyword-only `__new__` and
  sentinel `renderer_factory` / `emit` defaults, exactly like `TextElement`
  (`text.py:68`).
- Implement the `id` property; leave `_children()` at the empty default.
- Add `_set_<field>` setters for every patch field so inherited `apply_patch`
  works (`element_abc.py:124`).
- Keep `to_dict` / `from_dict` delegators (structural Protocol).
- **Render logic** stays a per-kind renderer object constructed by the tier's
  `RendererFactory`. It already exists for these kinds under
  `display/renderers` (`element_renderer.py:14`–`:30`). The ABC's `render()`
  simply calls it; nothing new is written in ImGui.
- `separator`'s empty-id default (`separator.py:25`) must move onto the ABC
  without the `dataclasses.replace` synthesis (`domain_pump.py:118`) — an ABC
  element cannot go through `replace`. This is why `_ABC_TYPES` raises for
  anonymous ABC ids today (`domain_pump.py:128`); separator forces that path to
  be replaced with explicit id assignment.

### Interactive leaf (slider, combo, input_text, input_number, radio, color_picker, selectable)

- Everything the display-only leaf needs, **plus**:
- Carry a typed interaction. Per `element-contract.md`, "Interaction Contract", value-changing
  inputs use `event_kind="value_changed"`, `action="changed"`, `value=<new>` —
  the shape `CheckboxElement` already models (`checkbox.py:95`).
- Register handlers via `add_handler(ValueChanged, ...)` at decode time (the
  Button/Checkbox decoders show the pattern: `button.py:203`, `checkbox.py:158`).
- Be wrappable by `wrap_handlers_for_remote`. Today that method hard-codes
  Button and Checkbox (`element_abc.py:231`,`:248`). Six more value-inputs need
  wrapping — see Decision (e): either extend the method per kind, or refactor so
  each interactive element declares its own `(event_type, event_kind, action)`.
- The `widget_value()` → `WidgetState` mirror in `SceneManager._apply_patch_set`
  (`manager.py:457`) is legacy display-local state. In the target, value state
  is Hub-authoritative and re-pushed whole; the migration must decide whether
  WidgetState survives as pure ephemeral view state (cursor position, focus) or
  is retired for value-bearing fields — Decision (c).

### Composite (group, tab_bar, collapsing_header, window, tree, modal, dialog✓)

- Override `_children()` to return the child Element tuple (`dialog.py:215`).
  `render()` then drives `begin()/end()` around children automatically.
- Own child lifetime and the observer/removal cascade (`element_abc.py:297`),
  as `DialogElement` does through its model.
- `tab_bar` and `tree` store children as `list[dict]` today (`layout.py:53`,
  `:107`), not typed Element lists. Migration must promote those to real child
  Elements (a `Tab` value class; `TreeNode` value class) so `_children()` can
  return Elements — otherwise the composite render template cannot recurse.
- `group.pages` / `page_source` (`layout.py:41`,`:45`) couple a container to a
  sibling combo's value. That cross-element linkage is view logic that must be
  re-expressed as either Hub-side built-in behavior or an observer relationship.
- `window` drag/resize position and `_dirty_windows` (`manager.py:481`) is
  Display-local ephemeral state. It must not become Hub-authoritative; the
  target's whole-tree resend would otherwise fight the user's drag.
- `modal` is interactive: it emits `"closed"`. It needs both the composite
  `_children()` and a close interaction routed to the Hub, like Dialog.

### Stateful rich-display (table, plot, draw)

- `table` (`table.py:74`) carries `TableFilter` (`table.py:18`) and
  `TableDetail` (`table.py:49`) plus row selection. `element-contract.md`,
  "Built-In Versus App-Defined Behavior", explicitly permits built-in filtering
  as lightweight element behavior. But
  *which row is selected* is a candidate for Hub authority (an app reads it to
  drive `openTicket`). Migration must split: view-only filter/search state stays
  Display-local; authoritative selection routes to the Hub. This is the single
  hardest kind — Decision (c). Row selection addresses rows by a stable `row_id`
  per [DES-045](../../DESIGN.md) — an agent-designated key or a synthesized stable
  key, replacing the legacy positional `row_index` — so this batch (B6,
  `lux-i3ag`) inherits the settled sub-element addressing contract rather than
  re-deciding it.
- `plot` (`plot_element.py:17`) is display-only but its `series` is
  `list[dict[str, Any]]` (`plot_element.py:27`) — an untyped anti-pattern the
  module docstring already flags. Migrating it onto the ABC is the moment to
  introduce typed series value classes (the draw-command family is the model).
- `draw` (`graphics.py:27`) is display-only with a fully-typed command family
  already OO-clean (curve/line/shape/text under `draw_commands_*.py`). The
  element wrapper migrates onto the ABC as a leaf; the command family does not
  change — Decision (d).

### Where the legacy render logic moves — in one sentence

Nowhere new. Rendering already lives in per-kind renderer objects
(`display/renderers`, `table_renderer`) for the basics/inputs families
(`element_renderer.py:14`) and in `ElementRenderer._RENDERERS` string-dispatch
for the composite/rich families (`element_renderer.py:104`). Migration rewires
which path constructs the renderer (ABC `render()` via injected
`RendererFactory` vs. `ElementRenderer` dispatch), it does not rewrite ImGui.
The end state retires the `_RENDERERS` dispatch table (`element_renderer.py:104`)
in favor of `renderer_factory(self)` per element.

## 5. Dependency / sequencing order

Establish the pattern on the lowest-risk kinds, then climb interactivity and
composite complexity. Each batch is a PR-equivalent slice. Order is defensible
because each batch reuses the exemplar proven by the batch before it.

**Batch 0 — reconcile the four exemplars (prerequisite).**
Fix the two discrepancies in §2a: add Checkbox to `_ABC_TYPES` (or document why
it is excluded) and confirm the Checkbox encode path. Without this the "migrated
set" is inconsistent and every later batch inherits the ambiguity.

**Batch 1 — basics display-only leaves** (image, separator, progress, spinner,
markdown). Reuses the `TextElement` template verbatim. `separator` forces the
anonymous-id resolution (`domain_pump.py:118`), which is the one novel piece.
Lowest risk; no handlers, no children.

**Batch 2 — interactive value inputs** (slider, combo, input_text,
input_number, radio, color_picker, selectable). Reuses the `CheckboxElement`
template. This batch forces Decision (e) — the wrap-seam refactor — because
seven kinds cannot each be a hand-written branch in `wrap_handlers_for_remote`
without that method becoming a god-method. `color_picker`'s `ImVec4` WidgetState
seeding (`manager.py:81`) is the awkward member; sequence it last in the batch.

**Batch 3 — simple composites** (group, tab_bar, collapsing_header,
collapsing/tree view state). Reuses the `DialogElement` `_children()` template.
Requires promoting `tab_bar.tabs` and `tree.nodes` from `list[dict]` to typed
child Elements (`layout.py:53`,`:107`). `group.pages`/`page_source` linkage
(Decision on cross-element view coupling) lands here.

**Batch 4 — stateful composites** (window, modal). `window` isolates the
Display-local-position question (Decision c); `modal` isolates the second
interactive-composite path after Dialog (the `"closed"` interaction).

**Batch 5 — draw + plot** (display-only rich). `draw` is nearly mechanical (the
command family is already OO-clean). `plot` bundles the `series` typing cleanup
(`plot_element.py:27`).

**Batch 6 — table** (last, alone). The only kind with built-in view behavior
*and* a candidate for Hub-authoritative selection. It should not share a PR with
anything else; it is the kind most likely to need a design amendment mid-flight.

**Batch 7 — retire the legacy path.** After every kind is an ABC subclass,
remove the `_RENDERERS` string dispatch (`element_renderer.py:104`), the
dual-write `DomainPump` (`domain_pump.py`), and the dataclass branch in
`SceneManager._apply_patch_set` (`manager.py:439`). This is the big-bang
*deletion* — but it deletes only after every kind has independently crossed —
see Decision (b).

## 6. Effort shape (relative, by PR count / complexity)

Not time — PR count and structural risk.

| Batch | Kinds | PR-equivalents | Complexity driver |
|-------|-------|----------------|-------------------|
| 0 reconcile | 4 (fix) | 1 | discrepancy audit, no new kinds |
| 1 basics | 5 | 1–2 | mechanical; separator id-synthesis |
| 2 inputs | 7 | 2–3 | **wrap-seam refactor** (Decision e) dominates; then 7 near-mechanical kinds |
| 3 simple composites | 3 | 2 | `list[dict]` → typed children promotion |
| 4 stateful composites | 2 | 2 | Display-local position (window); interactive modal |
| 5 draw + plot | 2 | 1–2 | plot `series` typing |
| 6 table | 1 | 2–3 | filter/selection authority split (Decision c) |
| 7 retire legacy | 0 (deletion) | 1–2 | remove `_RENDERERS`, `DomainPump`, dataclass patch branch |

Heaviest: Batch 2 (the wrap-seam refactor is a one-time architectural cost paid
by the first multi-input batch) and Batch 6 (table). Lightest: Batches 1 and 5.

## 7. Open design decisions — require operator ratification

Per the escalate-before-implementation rule, these are posed as concrete
decisions with a recommendation each. No implementation dispatches until these
are ruled on.

**(a) Do DISPLAY-ONLY elements get the full ElementABC, or a lighter
display-only base?**
The ABC carries a handler registry, `wrap_handlers_for_remote`, and the observer
surface (`element_abc.py:60`,`:213`,`:284`) that a display-only leaf never uses.
An `image` element with an empty `_handlers` dict and an unused wrap method is
dead surface on 12 kinds.
*Recommend:* **one ABC, no split.** The unused members cost nothing at runtime
(empty dict, no-op recursion), a single base keeps `_children()`/`render()`/
`apply_patch` uniform, and the contract doc treats "may be interactive" as a
per-kind property, not a type split (`element-contract.md`, "Core Definition"). A second base
class doubles the isinstance surface in `wrap_handlers_for_remote` and
`domain_pump` for no behavioral gain. Revisit only if a display-only kind must
forbid handler registration at the type level.

**(b) When/how does the legacy `SceneManager` + dual-write `DomainPump` get
retired — big-bang or incremental?**
The dual-write pump (`domain_pump.py:65`) mirrors native-kind scenes into the
domain Display but *skips any scene containing a non-native kind*
(`domain_pump.py:72`). So the two paths coexist per-scene today.
*Recommend:* **incremental crossing, big-bang deletion.** Migrate kinds family
by family (§5 Batches 1–6); each kind flips from the legacy path to the ABC path
independently, and mixed scenes keep working through the pump's skip rule. Only
after the *last* kind crosses (Batch 7) do we delete `_RENDERERS`
(`element_renderer.py:104`), `DomainPump`, and the dataclass branch of
`_apply_patch_set` (`manager.py:439`) in one deletion PR. Deleting the legacy
path earlier would strand any not-yet-migrated kind. This matches the refactoring
protocol: wire forward, delete the old path last, never leave two live paths for
the same kind.

**(c) How do stateful table and plot migrate given per-frame interaction
state?**
Table carries filter/search/row-selection; plot is static but its render reads
mutable `series`. The target says render calls never cross the wire and the Hub
is authoritative (`target.md:65`,`:38`), but it also permits built-in filtering
as element behavior (`element-contract.md`, "Built-In Versus App-Defined
Behavior").
*Recommend:* **split state by authority.** (1) *View-only* state — active filter
text, search string, scroll, expansion, window drag position — stays
Display-local ephemeral state and is NOT re-pushed by the Hub (whole-tree resend
must not clobber a user's in-progress filter). (2) *Authoritative* state — table
row *selection* that an app reads to publish `openTicket` — routes to the Hub as
an interaction and is re-pushed. Plot migrates as a display-only leaf with typed
series (no interaction). This keeps the Hub authoritative for business-relevant
state while honoring that a filter box is not business state. Ratify the
selection-is-authoritative half explicitly; it is the one place table stops being
display-only.

**(d) Do the draw-command families (curve/line/shape/text) migrate as elements
or stay a special case?**
The draw commands (`draw_commands_curve.py`, `_line`, `_shape`, `_text`) are a
typed, OO-clean value family *inside* `DrawElement` (`graphics.py:27`). They are
not elements — they have no id, no handlers, no independent render.
*Recommend:* **stay a value family; do not make them elements.** Only
`DrawElement` migrates onto the ABC (as a display-only leaf). The commands remain
composed value objects it owns. Promoting them to elements would give ids and
handler registries to line segments — surface the target explicitly warns
against (`element-contract.md`, "What Elements Must Not Become": "Elements must
not become … a dumping ground").
The draw command family is the *model* for how plot's `series` should be typed
(Decision c), not a migration target itself.

**(e) How does `wrap_handlers_for_remote` scale past two hard-coded kinds?**
Today the method branches on `isinstance(self, ButtonElement)` and
`isinstance(self, CheckboxElement)` (`element_abc.py:231`,`:248`). Batch 2 adds
seven interactive inputs; nine isinstance branches in one ABC method is a
god-method and couples the ABC to every concrete kind (a layering inversion —
the base importing its subclasses).
*Recommend:* **invert the seam — each interactive element declares its
interaction.** Give interactive kinds a small typed descriptor (event type,
`event_kind`, action source) and have `wrap_handlers_for_remote` iterate that
descriptor instead of switching on concrete type. This is a prerequisite for
Batch 2, not a follow-up — surfacing it during implementation would trigger an
audit + amendment cycle on seven kinds at once. Decide the descriptor shape at
design time. (This is the one decision that gates dispatch of Batch 2; the
others can be ratified per-batch.)

## 8. Proposed epic + child-bead structure

Ready to create in beads. All beads carry `--labels="repo:lux"`. The epic is
tracked as a parent; each batch is a child. Batch 0 and Decision (e) are
prerequisites and should be sequenced first.

**Epic:** `Migrate all element kinds onto the distributed Element-ABC / Hub-Display path`
Scope: move the 21 legacy dataclass kinds from the `SceneManager` + dual-write
`DomainPump` path onto `domain.element_abc.Element` + `HubDisplay`/`apply`,
retiring the legacy render dispatch when the last kind crosses. Blocks on
operator ratification of Decisions (a)–(e).

Child beads:

1. **Reconcile the four ABC exemplars** — fix `_ABC_TYPES` Checkbox omission
   (`domain_pump.py:32`) and verify the Checkbox encode path (`__init__.py:185`);
   land a per-kind ABC-membership table as the single source of truth.
2. **Wrap-seam inversion** — replace the hard-coded Button/Checkbox branches in
   `wrap_handlers_for_remote` (`element_abc.py:213`) with a per-element
   interaction descriptor. Prerequisite for the inputs batch. (Decision e.)
3. **Basics display-only leaves onto the ABC** — image, separator, progress,
   spinner, markdown; resolve anonymous-id synthesis for `separator`.
4. **Interactive value inputs onto the ABC** — slider, combo, input_text,
   input_number, radio, color_picker, selectable; consumes bead 2's descriptor.
5. **Simple composites onto the ABC** — group, tab_bar, collapsing_header;
   promote `tabs`/`nodes` `list[dict]` to typed child Elements.
6. **Stateful composites onto the ABC** — window (Display-local position) and
   modal (interactive `"closed"` path).
7. **Draw + plot onto the ABC** — draw as display-only leaf (command family
   unchanged); plot with typed series value classes.
8. **Table onto the ABC** — split view-only filter/search state (Display-local)
   from authoritative selection (Hub-routed). (Decision c.) Ships alone.
9. **Retire the legacy path** — delete `_RENDERERS` dispatch
   (`element_renderer.py:104`), `DomainPump` (`domain_pump.py`), and the
   dataclass branch of `_apply_patch_set` (`manager.py:439`) once every kind is
   an ABC subclass. (Decision b — big-bang deletion.)

## 9. Report status

Read-only audit. No code changed. Saved to
`docs/architecture/element-migration-audit.md`.
