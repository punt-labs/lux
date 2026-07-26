# Migrating `table` onto the Element-ABC / HubDisplay Path — the Basic Data Grid, Chrome by Composition (B6)

**Status:** design **ratified with amendments** — the operator ruled on all six
decisions ([Decisions — ruled](#decisions--ruled-by-the-operator)); this revision
records the ruling and updates the design and sketches accordingly.
Implementation dispatches against this amended design. No code in this document.
**Type:** migration design (interactive data widget; batch B6, the last real
migration — B7 is deletion).
**Element:** `table` — after this migration a **basic data grid** (columns, rows,
a key column, a selection). The filter bar, search box, status combos, and detail
panel are **not** table fields; they are compositions of existing primitives (see
§0, the composite shape).
**Exemplars copied:**

- **`CheckboxElement`** (`protocol/elements/checkbox.py:40`,
  `display/renderers/imgui/checkbox.py`) — the interactive leaf: a
  Hub-authoritative value, a `_remote_dispatch_specs`, a built-in state-sync
  handler, the Display-side wrap, Hub-side re-dispatch, a re-push.
- **`TreeElement`** (a `LeafKindSpec` in `abc_leaf_kinds.py`) — the data-bearing
  leaf: it paints structured data with **no child Elements**. A table's rows are
  data, so a table is a leaf in the same sense
  ([§2.3](#23-a-table-is-a-leaf-not-a-composite)).
- **`TabBarElement`** (`simple-composites-design.md`, DES-046) — the
  Hub-authoritative *discrete selection* that references a **stable sub-part id**
  and reconciles when the sub-part set changes. The table's row selection is the
  same machinery, generalized from one id to a **set** of stable `row_id`s.
- **`ModalModel`** (`protocol/elements/modal.py:47`) — the private model that owns
  a cohesive state cluster; `TableSelectionModel`
  (§7) mirrors it and owns the
  single/multi/none mode logic.

**Ground truth:** `docs/architecture/target/{target,ui-model,element-contract}.md`,
[DES-039](../../../DESIGN.md), [DES-040](../../../DESIGN.md) (`show` is the
universal render API; widget conveniences are skills composed from primitives),
[DES-041](../../../DESIGN.md), [DES-045](../../../DESIGN.md),
[DES-046](../../../DESIGN.md), [DES-047](../../../DESIGN.md), the render engine
(PR #239), and the code cited inline.

**The table is a general element, not the beads browser.** The beads browser
(`src/punt_lux/apps/beads.py` + the `lux:beads` skill) is one consumer and a
**smoke test**, not the specification. It is one instance of the grid + search +
detail composition, used below only as an example and the Level-6 demo.

---

## 0. The composite shape — a basic grid plus composed chrome

The operator ratified **composites over a class hierarchy** ("multiple types of
tables" are *named compositions*, not subclasses). This reshapes the migration:

- The **core `table` element is a basic data grid**: `columns`, `rows`, a
  `key_column`, a `selection` (mode + selected ids), grid render `flags`, optional
  `column_widths`, and `tooltip`. Nothing else.
- The **chrome leaves the element**. The filter bar, the search box, the status
  combos, and the detail panel are **compositions of existing primitives** —
  `input_text` (search), `combo` (categorical filters), the basic `table` (the
  grid), and a `group`/`text`/`markdown` region (detail) — assembled into one
  scene and wired through the interaction/publish machinery. This is
  [DES-040](../../../DESIGN.md)'s own doctrine: `show` is the universal render
  API, and widget conveniences are compositions expressed as skills, not fields
  bolted onto one fat element ("the elements are limited; the ways they combine
  are unlimited").
- **"Multiple types of tables" are named compositions**, not subclasses: a
  *basic grid* (the element alone), a *searchable list* (grid + search), a *data
  explorer* (grid + search + combos + detail), a *master/detail* (grid + detail).
  Each is a recipe over the same primitives, packaged as a skill
  ([§6.3](#63-what-show_table-and-the-beads-skill-compose)).

The rest of this document designs the basic grid (its selection, sort, geometry,
validation) and the composition layer that rebuilds the chrome.

---

## Decisions — ruled by the operator

All six were ruled. Each records the ruling and the resulting design. The settled
ADR constraints below the list are not reopened.

**Decision 1 — Business-event publish alongside the authoritative selection.
RULED: YES.** The selection routes through the D21 handler chain so a client can
attach an app handler and publish an app-level topic ("this could be input to an
agent"). Established pattern: `checkbox` (`checkbox_codec.py:81`) and `selectable`
(`selectable_codec.py:81`) register the built-in state-sync handler *and* install
extra wire `handlers`; the table does the same. Zero cost when no handler is
attached.

**Decision 2 — Selection cardinality. RULED: BOTH single and multi-select, "like
every other framework."** `selection_mode` of `none` / `single` / `multi`;
authoritative state is a **set** of selected `row_id`s (`selected_row_ids`), single
as the cardinality-1 case, `none` a display-only grid (subsuming the earlier
`is_selectable` predicate). `TableSelectionModel` owns the mode logic. **ImGui
supports this natively** ([§4, capability check](#imgui-multi-select-capability-check-decision-2)):
`begin/end_multi_select`, `MultiSelectFlags_.single_select`, ctrl-toggle /
shift-range / box-select. One honest constraint: ImGui keys selection by an
integer `SelectionUserData`, so the renderer translates current-display-order
index ↔ `row_id` each frame (Display-local, no functional limit). The detail
*composition* binds to the **last-selected** row (the anchor); single mode = the
one selected row.

**Decision 3 — Row-id source. RULED (clarified): `key_column` is a per-table
attribute defaulting to 0 — not a hard-coded column 0**, and it accepts **either a
column index or a column name** (`key_column: int | str = 0`). A string is matched
against `columns` and resolved to its index at decode. Recommend supporting the
name form — a name follows its column under column reorder while an index silently
points at a different column. The default stays the index `0` so the common case
needs no ceremony; `validate()` rejects a name absent from `columns` or an
out-of-range index.

**Decision 4 — Pagination vs native scroll. RULED: native ImGui scroll now;
pagination is a possible later additive layer, not closed.** The grid renders rows
in a native scroll region (Display-local scroll, list clipper draws only the ~30
visible rows at any row count). The legacy fixed 10-row `<< Prev` / `Next >>`
pager (`table_renderer.py:25`, `:286`) is not carried over — but if native scroll
proves insufficient (a remote Hub with a very large table, or a page-at-a-time
product need), pagination returns as an additive Display-local layer over the
scroll region. A future option, not a deleted feature.

**Decision 5 — Column sort authority. RULED: Display-local — with the reality
check the operator asked for.** Verified: **sort is dead today.** `sortable` maps
to `imgui.TableFlags_.sortable.value` (`table_renderer.py:409`) and nothing else —
no `table_get_sort_specs()` call, no reorder anywhere in the renderer; the header
shows sort arrows that never sort. The migration **makes sort real and
Display-local**: read `table_get_sort_specs()` (available in imgui-bundle 1.92.8)
each frame and stably reorder the *displayed* rows; the authoritative order is
untouched and the selection survives because it is keyed by `row_id`, not position.
Shipping a dead flag is the one option ruled out.

**Decision 6 — Chrome as composition; where filtering and the detail panel live.
RULED: composites, with Hub-side filtering as the v1 default.** The filter bar,
search box, status combos, and detail panel leave the element and become
compositions of primitives (§0). Two sub-rulings:

- **Filtering is Hub-side in v1.** A change to the composition's search
  `input_text` or a status `combo` routes through the interaction path to a
  Hub-side handler that owns the **unfiltered** row set and re-pushes the filtered
  subset into the basic table's `rows`. One source of truth: **the table always
  renders exactly the rows the Hub holds** — no Display-side hidden rows. The
  Display-local quick-filter (the `data-explorer` skill's zero-round-trip
  precedent) is documented as an alternative composition an agent *may* build, not
  the packaged default (§6.1).
- **The detail panel is a sibling element bound to the table's selection through
  the publish path.** The table fires `RowSelectionChanged`; a Hub-side
  composition handler reads the new anchor `row_id`, looks up that row's detail,
  and patches the sibling detail region — anchor = last-selected (Decision 2)
  ([§6.2](#62-the-detail-panel-as-a-sibling-element)).

### Settled constraints (not reopened)

- **Row selection is Hub-authoritative** — crosses the wire, the Hub owns it, the
  agent can drive it, a user gesture fires an event the Hub records, the Hub
  reconciles on structural change, re-pushed (DES-046).
- **Selection references stable `row_id`s, never positional `row_index`** — the
  legacy `row_index` (`table_renderer.py:165`) is the reorder bug this removes
  (DES-045). Multi-select is a *set* of `row_id`s, same rule.
- **Filter text and scroll offset are Display-local** — continuous in-progress
  input, never re-pushed (DES-046 / DES-041 decision 3). (This concerns the
  *typing* gesture; the resulting filter *predicate* is applied Hub-side per
  Decision 6, §6.1.)
- **Fork, don't mix** — the ABC `TableElement` takes the canonical name; the
  legacy dataclass is renamed `LegacyTableElement`, kept until B7 (DES-041).
- **`validate()` rides with the migration** (DES-039).
- **Writes are absolute, id-addressed, idempotent** — an agent-driven selection or
  a filtered row-set is a `SetProperty` / `apply_patch` on the Hub copy, re-pushed
  whole (DES-047).

---

## 1. Understanding restated (in the designer's words)

Clients submit a UI to the Hub; the Hub decodes it into typed objects and installs
them in `HubDisplay`; the Display holds a replica used only for rendering and input
capture; after a change the Hub re-sends the whole affected UI and the Display
replaces its copy (`target.md`). **UI state crosses IPC; render calls do not.**

For a migrated ABC basic `table`:

- **Crosses the Hub→Display boundary:** the serialized `TableElement` — its
  `columns`, `rows`, `flags`, `column_widths`, `key_column`, `selection_mode`,
  `selected_row_ids`, and its built-in selection state-sync handler. (No `filters`,
  no `detail` — those are separate composed elements now.)
- **Hub-authoritative:** the grid's *data* (`columns`, `rows`), its *selection
  mode*, and its *selection set*. For a filtered composition, the **unfiltered**
  superset lives in Hub-side composition state; the table's `rows` always holds the
  currently-visible subset.
- **Display-local:** the ImGui paint calls, and continuous in-flight view state —
  scroll offset and the current sort column/direction. A user's mid-type filter
  keystrokes are Display-local *while typing*; the committed filter value routes to
  the Hub-side filter handler (§6.1).

A user selection gesture crosses *back* as a `RemoteEventHandlerInvocation` whose
`value` carries the **full new set** of selected `row_id`s (one event per gesture,
even when a range/box gesture toggles many rows).

## 2. The exemplar mapping

### 2.1 Interactive leaf with Hub-authoritative selection — `checkbox`

`checkbox` holds `_value: bool`, declares `RemoteDispatchSpec(ValueChanged, ...)`,
registers a built-in handler mirroring the new value, re-dispatches on the Hub. The
table is the same interactive-leaf shape; its authoritative value is a **set** of
`row_id`s and it fires `RowSelectionChanged`. Every other D21 step is identical.

### 2.2 Discrete selection that names stable sub-part ids — `tab_bar`

`tab_bar` (DES-046) carries `_active_tab: str` naming a stable `tab_id`, reconciles
on tab-set change, reports it. The table's selection generalizes this from one id
to a set: it names `row_id`s (a row's `key_column` value), reconciles by **set
intersection** with the live rows, and reports the set. Not a new authority model —
`tab_bar`'s discrete selection, set-valued.

### 2.3 A table is a leaf, not a composite

DES-045: data sub-parts are **not** promoted to elements ("a `table` with 10 000
rows must not mint 10 000 elements"). The table has **no child Elements**:
`_children()` and `child_elements()` return `()`. It paints its rows in
`_paint_widget`, as `TreeElement` paints nested data. It registers as a
`LeafKindSpec`. (The *composition* that surrounds it — filter bar, detail region —
is made of sibling elements in a `group`; those are ordinary composite children of
the group, not children of the table.)

The one line: **the basic `table` is a `tree`-shaped data leaf that is also
`checkbox`-interactive (a Hub-authoritative selection set), and that selection is
`tab_bar`-shaped (stable sub-part ids, reconciled on structural change).**

## 3. The interaction the table fires

One new typed event, `RowSelectionChanged`, a frozen-slots dataclass carrying the
three identifying fields plus the full new selection set. It lands in a new
`domain/selection_interaction.py`, not `container_interaction.py`
(`container_interaction.py` already holds three classes — PY-OO-2 cap — and a table
is a leaf, not a container).

- **`RowSelectionChanged`** — payload `row_ids: tuple[str, ...]` (the full set after
  the gesture, ordered by selection recency so the last is the anchor). `EventKind`
  discriminator `"row_selection_changed"`.

Carrying the **full set** (not a per-row toggle) is deliberate: a range/box gesture
changes many rows in one act, so one absolute event per gesture is correct and
DES-047-shaped. Single-select is the length-≤1 case. The table declares its spec,
mirroring `checkbox.py:117`:

```python
def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
    return (RemoteDispatchSpec(RowSelectionChanged, self.id, "row_selection_changed"),)
```

### The full D21 loop (identical in shape to `tab_bar`)

1. **Built-in state-sync handler at decode.** `JsonTableDecoder` registers a
   serializable `_UpdateSelectionHandler(elem)` for `RowSelectionChanged`, whose
   `__call__` runs `elem.apply_patch({"selected_row_ids": list(event.row_ids)})` —
   a small class **inside `table_codec.py`** beside the decoder, mirroring
   `_UpdateActiveTabHandler` (`tab_bar_codec.py:37`). (Not the field-parameterised
   `ApplyPatchOnChange`, which reads `event.value`; this carries a set.)
2. **Display wraps the bucket** — `wrap_handlers_for_remote` collapses it into one
   remote-dispatch group; the Display copy never runs the real update.
3. **User selects rows** — `ImGuiTableRenderer` (via `begin/end_multi_select`)
   resolves ImGui's selection requests to the new `row_id` set, sees it differs
   from `elem.selected_row_ids`, constructs `RowSelectionChanged(...)`, calls
   `elem.fire(event)`.
4. **`fire` sends one remote invocation** — `RemoteDispatchGroup.__call__` grows one
   branch: `RowSelectionChanged → value = list(event.row_ids)`.
5. **Hub re-dispatches** — `domain/hub/clients.py` grows one branch:
   `"row_selection_changed" → RowSelectionChanged(..., row_ids=tuple(value))`, fires
   on the Hub copy, the built-in handler updates the authoritative set;
   `Display._build_event` grows the same branch.
6. **Hub re-pushes the whole scene** — the table carries the new `selected_row_ids`;
   any bound detail region updates through its own composition handler (§6.2).

### The agent-drive (write) path

The agent drives selection by `apply_patch({"selected_row_ids": [...]})` (or a
fresh `show()`) + re-push. The ImGui adapter *honours* `elem.selected_row_ids` each
frame (syncs its Display-local selection storage from the authoritative set); the
"last honoured set" is Display-local bookkeeping in `WidgetState`, distinguishing a
fresh Hub write (honour) from a user gesture (fire) — the tab_bar discipline
(`simple-composites-design.md` §4.7).

### Reconciliation on structural change — set intersection

When the row set changes (including a filter re-push, §6.1), the Hub keeps
`selected_row_ids` valid by intersecting with the live row ids, preserving order:

- **Rows added** → every selected id still names a live row → unchanged.
- **Selected rows removed** → removed ids drop; survivors kept in order (the
  DES-045 payoff, for a set).
- **A selected row's cell changes** (its `key_column` value unchanged) → unchanged.
- **A selected row filtered out** (its id no longer in the re-pushed rows) → drops
  from the selection; the survivors stay selected. A composition that wants a
  filtered-out selection to *return* when the filter clears preserves that intent
  in its own Hub-side handler (§6.1) — it is composition state, not core-grid state.

Reconciliation lives on the element (in `_set_rows` and at decode), delegating to
`TableSelectionModel.reconcile`. `validate()` asserts: **every id in
`selected_row_ids` names a live row; mode `single` holds ≤ 1; mode `none` is
empty.**

## 4. Scope-bound sub-questions (answered)

### ImGui multi-select capability check (Decision 2)

Verified against the installed `imgui-bundle` **1.92.8** (`uv run --extra display`):

| Capability | Present? | Symbol |
|---|---|---|
| Multi-select scope | yes | `begin_multi_select` / `end_multi_select`, `MultiSelectIO` |
| Single-select via the same API | yes | `MultiSelectFlags_.single_select` |
| Per-item selection tagging | yes | `set_next_item_selection_user_data` |
| Range (shift) + box select | yes | `MultiSelectFlags_.box_select1d` / `box_select2d` |
| Clear-on-escape, no-select-all | yes | `MultiSelectFlags_` |
| Row selectable spanning columns | yes | `SelectableFlags_.span_all_columns` |
| Selection storage helper | yes | `SelectionBasicStorage`, `SelectionExternalStorage` |

**No functional gap** — single vs multi is the `single_select` flag. **One honest
constraint:** ImGui identifies items by an integer `SelectionUserData`, not our
string `row_id`. The renderer tags each row's selectable with its
current-display-order index via `set_next_item_selection_user_data(index)`, applies
ImGui's SetRange/SetAll/Clear requests against a Display-local index set, and
translates changed indices → `row_id`s (through the current display order) before
firing `RowSelectionChanged`. Display-local, total, no limit; recomputed each frame
so it composes with Display-local sort and Hub-side filtering alike.

### Legacy feature carry-over — what the basic grid keeps, what leaves

| Legacy feature | Where it lands |
|---|---|
| `columns`, `rows` | **Core grid field** — kept. |
| `key_column` (int or name) | **Core grid field** — new (Decision 3). |
| Row selection | **Core grid: Hub-authoritative set** (`selection_mode` + `selected_row_ids`). |
| `flags` (`borders`, `row_bg`, `resizable`, `sortable`, `copy_id`) | **Core grid field, retyped** — a `TableFlags` value object (kills the `list[str]`-with-a-comment). |
| `column_widths` | **Core grid field** — kept (grid layout hint). |
| Column sort | **Core grid, Display-local, made real** (Decision 5). |
| Manual pagination | **Not carried over** — native scroll (Decision 4). |
| **Filters (`filters` bar, search, combos)** | **LEAVES the element** — a composition of `input_text` + `combo`, filtered Hub-side (§6.1). |
| **Detail panel (`detail`)** | **LEAVES the element** — a sibling `group`/`text`/`markdown` region bound to selection (§6.2). |

### Column sort — the reality check (Decision 5)

`table_renderer.py:409` sets the ImGui flag and nothing reads a sort spec or
reorders — sort does nothing today. The migration makes it real, Display-local:
read `table_get_sort_specs()` each frame, stably reorder the displayed rows, leave
the authoritative order and the row_id-keyed selection untouched.

### `TableSelectionModel` / private-model split

A private `TableSelectionModel` owns `selection_mode`, `selected_row_ids`, the
anchor, and the select/reconcile/cardinality logic — mirroring `ModalModel`.
`TableElement` composes it (PY-IC-1). It keeps the mode logic in one place and the
element focused.

### How a 10 000-row grid crosses the wire under whole-UI resend

- **Small grid (~50 rows × 5 cols):** ≈ 4 KB (no detail field now); re-push well
  under 1 ms locally; per-gesture re-push imperceptible.
- **10 000 rows × 5 cols, ~15 chars/cell:** ≈ 0.8 MB / ≈ 1 MB JSON; local re-push
  single-digit to low-tens of ms — a one-off gesture reaction, not per-frame;
  ImGui's clipper still draws ~30 rows. A 1 000-id multi-selection ≈ 10 KB.
- **v1 (local):** no diff protocol (`target.md`). A Hub-side filter re-push of a
  large grid is the same one-off cost class as any row change.
- **Remote, bounded answer:** ~1 MB per gesture over the network (~80 ms at
  100 Mbps) → a future `SetProperty(rows | selected_row_ids)` delta; deferred
  v2-remote optimization, out of scope.

### Geometry capture — leaf, automatic

The grid registers as a `LeafKindSpec`; its renderer subclasses `LeafRenderer`,
whose `paint()` records the leaf's whole rect via the geometry `measuring` group
(`display/renderers/imgui/leaf.py`). Inline content, no draggable rect — the
window/modal/dialog geometry work does not apply.

## 5. Fork, don't mix — and the composition lands with the element

Per DES-041 decision 2, the new ABC class takes the canonical name; the legacy
dataclass is renamed:

- `protocol/elements/table.py` — `TableElement` → `LegacyTableElement`, keeping its
  dataclass shape **including `filters` and `detail`** and its `TableFilter` /
  `TableDetail` value classes. The legacy class and its renderer stay until B7.
- `display/table_renderer.py` — retained for `LegacyTableElement` until B7.

**The one hard consequence of Decision 6 — the compositions land in B6, not later.**
There is one `table` kind. The moment the ABC basic grid takes the canonical name,
`filters` and `detail` are no longer table fields, so every producer that sends
them today — the `show_table` tool/skill, the `beads` skill, the `data-explorer`
skill, and `apps/beads.py` — **must be rebuilt as compositions in the same change**
(org rule: breaking changes update all callers in the same PR; no shims,
PL-PP-1). This is not an operator fork (fork-don't-mix forbids the alternatives —
an accept-and-ignore shim or keeping the legacy fat table canonical are both
mixing/shimming). It is a scope fact: **B6 delivers the basic grid element *and*
the rebuilt grid+search+detail composition together.** The legacy class remains
only as the not-yet-deleted fork tail, decoded by nothing once the compositions
cut over.

## 6. The composition layer

### 6.1 Filter ownership — Hub-side in v1

The packaged composition (`show_table`, §6.3) assembles a `group` holding a filter
bar (`input_text` for search, `combo`(s) for categoricals) above the basic
`table`. Filtering is **Hub-side**:

1. The full **unfiltered** dataset lives in Hub-side composition state, not in the
   table element.
2. A committed change to the search `input_text` (`value_changed`) or a status
   `combo` (`value_changed`) routes through the D21 interaction path to a Hub-side
   **filter handler** that owns the unfiltered rows.
3. The handler recomputes the visible subset (substring match on the searched
   columns; exact match on a combo column) and `apply_patch`es the table's `rows`.
4. The Hub re-pushes; the table renders exactly the rows the Hub holds — **one
   source of truth, no Display-side hidden rows.** Selection reconciles by set
   intersection (§3): a selected row still visible stays selected.

The filter handler is generic (substring / exact match), so it is a reusable
**composition-provided Hub-side handler**, not per-agent business logic — it does
not round-trip to the agent. (An agent that needs a *custom* predicate — numeric
range, cross-field, external lookup — wires its own handler or the `recv()` /
`update()` loop, exactly the `data-explorer` skill's "separate elements, advanced"
path.)

**The documented alternative (not the packaged default): a Display-local
quick-filter.** The `data-explorer` skill's other precedent is zero-round-trip
Display-local filtering. An agent *may* build a composition that filters on the
Display for instant feedback, accepting that the grid then renders a superset and
the filter hides rows Display-side (two views of the row set instead of one). The
packaged compositions use the Hub-side default for the single-source-of-truth
property; the Display-local path is available but not the default. (A future
first-class Display-local filter overlay on the grid is possible additive work,
the same shape as Decision 4's pagination note — flagged, not built.)

### 6.2 The detail panel as a sibling element

The detail panel is a **sibling element bound to the table's selection through the
publish path**, not a table field:

- The composition places a detail region beside/below the grid — a `group` holding
  a `text` heading, a small 2-column field/value grid (a basic `table` or paired
  `text`), and a `markdown`/`text` body.
- The table fires `RowSelectionChanged`; a Hub-side **detail-binding handler**
  (composition-provided, on the table's selection interaction) reads the new
  **anchor** `row_id` (last-selected, Decision 2), looks up that row's detail from
  composition state, and `apply_patch`es the sibling detail region's content.
- The Hub re-pushes; the detail region shows the anchor row. Empty selection with a
  detail present → the anchor is the seeded first row (§3 reconciliation seeds the
  composition's initial selection).

This is the DES-040 business-logic-via-handler pattern: the *view* half (which row
is selected) is the grid's built-in behavior; the *consequence* (render its detail)
is wired by the composition. Recommended over the rejected alternative (detail as a
table field), and it generalizes — the same publish binding drives any
selection-reactive sibling (a chart, an action bar), not only a detail panel.

### 6.3 What `show_table` and the beads skill compose

After this migration, `show_table` is a **composition builder** (a skill /
convenience over `show`, per DES-040), not a fat-element emitter:

- **Inputs** (unchanged agent ergonomics): columns, rows, optional filter specs,
  optional detail data.
- **Composes:** a `group` (`layout="rows"`) stacking a filter bar (`input_text`
  search plus `combo` categoricals), the basic `table`, and a detail region
  (`group`/`text`/`markdown`); wires the Hub-side filter handler over the full rows
  (§6.1) and the detail-binding handler on the table's selection (§6.2); and calls
  `show()`.
- **`beads` skill:** the same grid + search + detail composition with beads data
  (columns ID/Title/Status/P/Type; search on ID+Title; combos on Status/Type;
  detail = fields grid + description body; `key_column` = column "ID"). One
  instance of the composition — a smoke test.
- **`data-explorer` skill:** already documents both filter paths; it is updated to
  compose the basic grid + Hub-side chrome as the default, keeping its "separate
  elements / recv-update" section as the custom-predicate advanced path.
- **Named table compositions** are documented recipes, not element subtypes:
  *basic grid*, *searchable list*, *data explorer*, *master/detail*.

## 7. The write set

The core grid **shrinks**; the chrome moves to the composition layer.

**Core grid — new (the basic `table` element):**

- `src/punt_lux/protocol/elements/table.py` — the ABC `TableElement` (canonical
  name) composing `TableSelectionModel`. Fields: `columns`, `rows`, `flags`
  (`TableFlags`), `column_widths` (optional), `key_column` (int-or-name → resolved
  index), `selection_mode`, `selected_row_ids`, `tooltip`. **No `filters`, no
  `detail`.** Overrides `id`, `kind`, `_children()` (`()`), `validate()`,
  `_remote_dispatch_specs()`, `resolved_props()`; setters `_set_rows` (reconcile),
  `_set_columns`, `_set_selected_row_ids`, `_set_selection_mode`.
- `src/punt_lux/protocol/elements/table_selection_model.py` — `TableSelectionModel`
  (mode, ordered selected tuple, anchor, `apply` / `reconcile`, cardinality).
- `src/punt_lux/protocol/elements/table_flags.py` — `TableFlags` value object.
- `src/punt_lux/protocol/elements/table_codec.py` — `JsonTableEncoder` /
  `JsonTableDecoder` **and** the built-in `_UpdateSelectionHandler` (inside the
  codec, mirroring `_UpdateActiveTabHandler`); resolves `selection_mode` (a bare
  grid defaults `none`) and the `key_column` int-or-name.
- `src/punt_lux/domain/selection_interaction.py` — `RowSelectionChanged`.
- `src/punt_lux/display/renderers/imgui/table.py` — `ImGuiTableRenderer`
  (`@final`, `LeafRenderer[TableElement]`): grid setup, column weights, the
  scrollable row region (native scroll + list clipper), the multi-select flow
  (`begin/end_multi_select`, index↔row_id), Display-local sort
  (`table_get_sort_specs()` + stable reorder), selection honour/fire. **No filter
  bar, no detail rendering** — roughly the **~290 lines** of legacy filter, combo,
  pagination, and detail rendering (`table_renderer.py` `_render_filter_*`,
  `_apply_table_filters`, `_filter_*`, `_render_table_pagination`,
  `_render_table_detail`, `_render_detail_field_grid`) do **not** cross to the core
  renderer.

**`TableFilter` / `TableDetail` fate:** they stay in the **legacy** module with
`LegacyTableElement` (they are legacy dataclass fields), deleted with the legacy
path in **B7**. They are *not* re-created for the ABC element and *not* reused by
the composition (the composition builds chrome from real `input_text` / `combo` /
`group` primitives, not from these value classes). ~91 lines of `TableFilter` +
`TableDetail` never migrate.

**Composition layer — new:**

- The `show_table` composition builder + the generic Hub-side **filter handler**
  and **detail-binding handler** (serializable handlers the composition registers,
  parallel in shape to the built-in state-sync handlers). Exact module layout is
  the implementer's call (a `compositions/` helper the skill and `apps/beads.py`
  share is the natural home); the design fixes the *ownership* (Hub-side,
  composition-provided), not the file.
- `apps/beads.py` — rebuilt to compose the basic grid + Hub-side chrome.
- `skills/beads/SKILL.md`, `skills/data-explorer/SKILL.md`, and the `show_table`
  surface — updated to the composition (org rule: callers update in the same PR).

**Amended (interaction wiring):**

- `domain/interaction.py` (`EventKind` += `"row_selection_changed"`);
  `domain/handlers/remote_dispatch.py`, `domain/hub/clients.py`,
  `domain/display.py` (one dispatch branch each);
  `protocol/elements/abc_leaf_kinds.py` (`LeafKindSpec` for `table` + selection
  handler_builder); `protocol/element_factory.py` (fork branch);
  `protocol/elements/__init__.py`, `encoder_factory.py`,
  `display/renderers/imgui/factory.py`; `.oo-baseline.json`, `.oo-audit.jsonl`.

Legacy deletion (`LegacyTableElement`, `table_renderer.py`, `TableFilter`,
`TableDetail`) is **B7**.

## 8. Type sketches (recommended shape)

```python
# domain/selection_interaction.py (new) — mirrors TabChanged, set-valued
@dataclass(frozen=True, slots=True, init=False)
class RowSelectionChanged:
    """Full new set of selected row ids, ordered by recency (last = anchor)."""

    scene_id: SceneId
    element_id: ElementId
    owner_id: ClientId
    row_ids: tuple[str, ...]
    kind: ClassVar[Literal["row_selection_changed"]] = "row_selection_changed"
    # __new__ / from_wire as TabChanged (object.__setattr__ over the slots)


# protocol/elements/table_flags.py — kills the list[str]-with-a-comment
@dataclass(frozen=True, slots=True)
class TableFlags:
    borders: bool = True
    row_bg: bool = True
    resizable: bool = False
    sortable: bool = False
    copy_id: bool = False

    @classmethod
    def from_wire(cls, flags: list[str]) -> Self: ...
    def to_wire(self) -> list[str]: ...


# protocol/elements/table_selection_model.py — private, mirrors ModalModel
SelectionMode = Literal["none", "single", "multi"]


class TableSelectionModel:
    """Selection state + cardinality. ``none`` = display-only (no selection, no
    key-column constraint); ``single`` keeps <= 1; ``multi`` holds a set.
    ``_selected`` is ordered by recency so ``anchor`` (its last) is the row a
    bound detail composition shows."""

    _mode: SelectionMode
    _selected: tuple[str, ...]

    def __new__(cls, *, mode: SelectionMode = "none",
                selected: tuple[str, ...] = ()) -> Self: ...

    @property
    def mode(self) -> SelectionMode: ...

    @property
    def is_selectable(self) -> bool:
        return self._mode != "none"

    @property
    def selected_row_ids(self) -> tuple[str, ...]:
        return self._selected

    @property
    def anchor(self) -> str:
        return self._selected[-1] if self._selected else ""

    def apply(self, row_ids: tuple[str, ...]) -> None:
        """Set from a user gesture / agent drive. none -> empty; single -> last
        only; multi -> the full ordered deduplicated set."""

    def reconcile(self, live_ids: tuple[str, ...]) -> None:
        """Keep only ids still present, order preserved."""


# protocol/elements/table.py — the basic grid (checkbox-interactive, tree-data-shaped)
class TableElement(Element):
    """A basic data grid: a leaf (no child elements) with a Hub-authoritative
    row selection set. No filters, no detail — those are composed siblings.
    tooltip stays str | None — absence is the documented contract."""

    _id: str
    _columns: tuple[str, ...]
    _rows: tuple[tuple[object, ...], ...]
    _flags: TableFlags
    _column_widths: tuple[float, ...] | None  # optional grid layout hint
    _key_column: int                           # resolved from int-or-name at decode
    _selection: TableSelectionModel
    _tooltip: str | None
    _kind: Literal["table"]

    @property
    def selection_mode(self) -> SelectionMode:
        return self._selection.mode

    @property
    def selected_row_ids(self) -> tuple[str, ...]:
        return self._selection.selected_row_ids

    def _row_id(self, row: tuple[object, ...]) -> str:
        return str(row[self._key_column])

    def _set_rows(self, value: object) -> None:
        self._rows = PatchField("rows").as_rows(value)
        self._selection.reconcile(tuple(self._row_id(r) for r in self._rows))

    def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
        return (RemoteDispatchSpec(RowSelectionChanged, self.id, "row_selection_changed"),)

    def validate(self) -> tuple[ValidationError, ...]:
        """Rows-vs-columns + renderable cells always. When selectable
        (mode != "none"): the key column resolves, its values are non-empty and
        unique, every selected id names a live row, and mode "single" holds <= 1.
        A display-only (mode "none") grid has no key-column constraint — a repeated
        key column is fine."""

    def resolved_props(self) -> Mapping[str, object]:
        return {
            "columns": list(self._columns),
            "row_count": len(self._rows),
            "selection_mode": self._selection.mode,
            "selected_row_ids": list(self._selection.selected_row_ids),
            "anchor_row_id": self._selection.anchor,
            "key_column": self._key_column,
            "tooltip": self._tooltip,
        }
```

## 9. Verify plan — Levels 1–6

Write expected values first; drive the real entry point; assert against live state.
`make check` passes; `.oo-baseline.json` + `.oo-audit.jsonl` staged in the commit.

1. **Level 1 — serialization roundtrip.** Basic grids in each mode
   (`none`/`single`/`multi`), rows with a unique key column, `key_column` as a
   **name** and as an **index**, explicit and empty `selected_row_ids`, one nested
   in a `group` → `to_dict`/`from_dict` → assert equal.
2. **Self-validation (DES-039).**
   - **always** → ragged row, non-scalar cell, `key_column` name absent / index out
     of range → error; via `show()`, `client.show.assert_not_called()`.
   - **selectable only** → mode `single`/`multi` with a duplicate/empty key, a
     selected id naming no row, or `single` with two ids → error.
   - **regression guard (mode `none`)** → a display-only grid whose key column
     repeats (a `{status, count}` aggregate) validates to `()` and renders.
   - **structural guard** → the DES-039 container-guard test passes
     (`child_elements() == ()`).
3. **Level 2 — wire roundtrip.** A multi-select grid in a `SceneMessage` →
   serialize/deserialize → equal; assert the built-in `_UpdateSelectionHandler`
   survived in the pickled blob.
4. **Level 3 — Hub/Display crossing.** Install → push → equal replica;
   `bind_renderer_factory` rebound the factory.
5. **Level 4 — the harness Scenarios.**
   - **Interactive multi-select** `table_multi_select_progress`: a `multi` grid;
     inject `row_selection_changed` carrying two ids (range gesture); the built-in
     handler sets the Hub set; assert the re-push carries it
     (`PropAfterDispatch(field="selected_row_ids", value=[...])`); a wire `handlers`
     entry publishes `rows_opened`; the agent advances a `progress` — Decision 1's
     publish path.
   - **Composed chrome — Hub-side filter** `table_search_filters_hub_side`: the
     composition (`input_text` search + basic `table`) with a selected row that
     matches the query. Inject a `value_changed` on the search input; the Hub-side
     filter handler recomputes the visible rows and `apply_patch`es the table's
     `rows`; assert the table now holds only matching rows **and the selected row
     (still matching) stays selected** (selection intact via set-intersection
     reconciliation). This is Decision 6's v1 path end to end.
   - **Reconcile-on-reorder** `table_reorder_keeps_selection`: select `{a, c}`,
     re-push rows reordered with `b` removed and a row inserted; assert
     `selected_row_ids == (a, c)`.
6. **Level 5 — introspection.** `inspect_scene` → `render_path == "abc"`;
   `resolved_props` reads `columns`, `row_count`, `selection_mode`,
   `selected_row_ids`, `anchor_row_id`. After the interactive Scenario, the reported
   set reflects the interaction.
7. **Level 6 — live visual confirmation.** `make restart`; render a `multi` grid via
   `show_table`, and the beads board via `lux:beads` (smoke test). Confirm by eye +
   `screenshot`: click selects, ctrl-click toggles, shift-click ranges, box-select
   works; a real column sort reorders rows and keeps the selection; the composed
   search box filters the grid **Hub-side** (the table shows only matching rows) and
   selection survives; clicking a row updates the sibling detail region; an
   agent-driven `selected_row_ids` re-push moves the highlight with no gesture.
   Capture `inspect_scene` + `list_recent_events`; **operator confirms**.

## 10. Report status

Design ratified with the operator's six rulings and updated accordingly, including
the composite reshaping (Decision 6): the core `table` is now a **basic data grid**,
and the filter bar, search box, status combos, and detail panel are **compositions
of primitives**, filtered Hub-side in v1 with the detail panel a selection-bound
sibling. The core write set shrinks (~290 lines of filter/detail/pagination
rendering and ~91 lines of `TableFilter`/`TableDetail` do not migrate); the
compositions (`show_table`, `beads`, `data-explorer`) rebuild in the same change
per fork-don't-mix and the update-all-callers rule. No production code written.
Saved to `docs/architecture/migration/table-design.md`. Implementation dispatches
against this amended design.
