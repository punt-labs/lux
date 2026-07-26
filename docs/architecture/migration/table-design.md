# Migrating `table` onto the Element-ABC / HubDisplay Path — the Last Data Widget (B6)

**Status:** design **ratified with amendments** — the operator ruled on all five
decisions ([Decisions — ruled](#decisions--ruled-by-the-operator)); this revision
records the ruling and updates the design and sketches accordingly.
Implementation dispatches against this amended design. No code in this document.
**Type:** migration design (interactive data widget; batch B6, the last real
migration — B7 is deletion).
**Element:** `table` (columns + rows, built-in filters, sorting, row selection,
detail panel).
**Exemplars copied:**

- **`CheckboxElement`** (`protocol/elements/checkbox.py:40`,
  `display/renderers/imgui/checkbox.py`) — the interactive leaf: a
  Hub-authoritative value, a `_remote_dispatch_specs`, a built-in state-sync
  handler, the Display-side wrap, Hub-side re-dispatch, a re-push.
- **`TreeElement`** (registered as a `LeafKindSpec` in
  `abc_leaf_kinds.py`) — the data-bearing leaf: it paints structured, nested
  data with **no child Elements**. A table's rows are data, not elements, so a
  table is a leaf in the same sense (see [§2.3](#23-a-table-is-a-leaf-not-a-composite)).
- **`TabBarElement`** (`simple-composites-design.md`, DES-046) — the
  Hub-authoritative *discrete selection* that references a **stable sub-part id**
  (`tab_id`) and reconciles when the sub-part set changes. The table's row
  selection is the same machinery, generalized from one id to a **set** of stable
  `row_id`s.
- **`ModalModel`** (`protocol/elements/modal.py:47`) — the private model that
  owns a cohesive state cluster; the `TableSelectionModel`
  ([§7](#7-type-sketches-recommended-shape)) mirrors it and owns the
  single/multi/none mode logic.

**Ground truth:** `docs/architecture/target/{target,ui-model,element-contract}.md`,
[DES-039](../../../DESIGN.md) (self-validating elements),
[DES-041](../../../DESIGN.md) (fork, don't mix; order by testability),
[DES-045](../../../DESIGN.md) (stable sub-element id, never a positional index),
[DES-046](../../../DESIGN.md) (view-state locality: discrete selections are
Hub-authoritative, continuous input is Display-local),
[DES-047](../../../DESIGN.md) (the Hub-authoritative write path), the render
engine (PR #239), and the code cited inline.

**The table is a general element, not the beads browser.** The beads browser
(`src/punt_lux/apps/beads.py` + the `lux:beads` skill) is one consumer and a
**smoke test**, not the specification. The design below is for a general data
table — single *and* multi-select, sortable, keyed by a per-table column — and
beads is used only as a concrete example and the Level-6 demo, never as the
scope boundary.

---

## Decisions — ruled by the operator

All five were ruled. Each records the ruling and the resulting design. The
settled ADR constraints below the list are not reopened.

**Decision 1 — Business-event publish alongside the authoritative selection.
RULED: YES.** The selection routes through the D21 handler chain so a client can
attach an app handler and publish an app-level topic ("this could be input to an
agent"). This is the established pattern: `checkbox` (`checkbox_codec.py:81`) and
`selectable` (`selectable_codec.py:81`) both register the built-in state-sync
handler *and* install extra wire `handlers`; the table does the same. Cost is
zero when no handler is attached — the built-in state-sync handler runs alone.

**Decision 2 — Selection cardinality. RULED: BOTH single and multi-select, "like
every other framework."** The table supports a `selection_mode` of `none`,
`single`, or `multi`; the authoritative state is a **set** of selected `row_id`s
(`selected_row_ids`), with single-select as the cardinality-1 case and `none` as
a display-only table (subsuming the earlier `is_selectable` predicate). The
private `TableSelectionModel` owns the mode logic. **ImGui supports this
natively** — the capability check ([§4, ImGui multi-select](#imgui-multi-select-capability-check-decision-2))
confirms `begin_multi_select` / `end_multi_select`, `MultiSelectFlags_.single_select`
for the single case, and ctrl-toggle / shift-range / box-select built into the
request flow. The one honest constraint: ImGui identifies selected items by an
integer `SelectionUserData`, not by our string `row_id`, so the renderer
translates between the current-display-order index and the `row_id` each frame —
a Display-local mapping with no functional limit. The detail panel binds to the
**last-selected** row (the selection *anchor*); in single mode that is the one
selected row (see [§3, detail binding](#detail-panel-binding-under-multi-select)).

**Decision 3 — Row-id source. RULED (clarified): `key_column` is a per-table
attribute defaulting to 0 — not a hard-coded column 0.** An agent sets
`key_column` per table; it defaults to `0` only as the common case. Column 0 is
never assumed by the design. Additionally, `key_column` accepts **either a column
index or a column name** (`key_column: int | str = 0`): a string is matched
against `columns` and resolved to its index at decode. **Recommend supporting the
name form**, because a name follows its column under column reorder while an index
silently points at a different column — the same brittleness DES-045 removes at
the row level, applied to columns. The default stays the index `0` so the common
case needs no ceremony; `validate()` rejects a name not in `columns` or an
out-of-range index.

**Decision 4 — Pagination vs native scroll. RULED: start with native ImGui
scroll; pagination is a possible later additive layer, not a closed question.**
The migration renders rows in a native ImGui scroll region (Display-local scroll,
list clipper draws only the ~30 visible rows at any row count). The legacy fixed
10-row `<< Prev` / `Next >>` pager (`_ROWS_PER_PAGE = 10` at
`table_renderer.py:25`, `:286`) is not carried over — **but pagination is not
removed-and-closed**: if native scroll proves insufficient (a remote Hub with a
very large table where even clipped rendering plus the whole-UI resend is heavy,
or a product need for page-at-a-time browsing), pagination returns as an
*additive* Display-local layer — a page window over the rows — on top of the
scroll region. Framed as a future option, not a deleted feature.

**Decision 5 — Column sort authority. RULED: Display-local view-state — with a
reality check the operator asked for.** Verified: **sort is dead today.** The
legacy `sortable` flag maps to `imgui.TableFlags_.sortable.value`
(`table_renderer.py:409`) and nothing else — there is no `table_get_sort_specs()`
call and no row reordering anywhere in `table_renderer.py`, so the flag draws
clickable sort arrows in the header that never reorder the rows. The migration
**makes sort real and Display-local**: the renderer reads `table_get_sort_specs()`
(available in imgui-bundle 1.92.8) each frame and stably reorders the *displayed*
rows; the authoritative row order is untouched, and the selection survives a sort
because it is keyed by `row_id`, not position. Recommend make-it-real over
dropping the flag — a general data table should sort, the cost is one API call
plus a stable sort of the display list, and it stays Display-local (consistent
with this ruling). Shipping a dead flag is the one option ruled out.

### Settled constraints (not reopened)

- **Row selection is Hub-authoritative** — it crosses the wire, the Hub owns it,
  the agent can drive it, a user gesture fires an event the Hub records, the Hub
  reconciles it on structural change, and the change is re-pushed (DES-046).
- **Selection references stable `row_id`s, never positional `row_index`** — the
  legacy `row_index` (`table_renderer.py:165`) is the latent reorder bug this
  migration removes (DES-045). Multi-select is a *set* of `row_id`s, same rule.
- **Filter text and scroll offset are Display-local** — continuous in-progress
  input, never re-pushed (DES-046 / DES-041 decision 3).
- **Fork, don't mix** — the ABC `TableElement` takes the canonical name; the
  legacy dataclass is renamed `LegacyTableElement` and its renderer retained
  until B7 deletes the legacy path (DES-041).
- **`validate()` rides with the migration** — the table gains its
  component-appropriate `validate()` as it crosses (DES-039).
- **Writes are absolute, id-addressed, idempotent** — an agent-driven selection
  is a `SetProperty` / `apply_patch({"selected_row_ids": [...]})` on the Hub copy,
  re-pushed whole; the full set crosses, not a delta (DES-047).

---

## 1. Understanding restated (in the designer's words)

Clients submit a UI to the Hub; the Hub decodes it into typed objects and
installs them in `HubDisplay`, the authoritative store for state, ownership, and
dispatch; the Display holds a full replica used only for rendering and input
capture; after a change the Hub re-sends the whole affected UI and the Display
replaces its copy (`target.md`). The load-bearing rule: **UI state crosses IPC;
render calls do not**.

For a migrated ABC `table`:

- **Crosses the Hub→Display boundary:** the serialized `TableElement` — its
  `columns`, `rows`, `filters`, `detail`, `flags`, `key_column`, `selection_mode`,
  and its built-in selection state-sync handler. A top-level ABC element crosses
  as one pickled blob; the built-in handler travels inside it, which is what lets
  the Display wrap the selection interaction for remote dispatch.
- **Hub-authoritative:** the table's *data* (`columns`, `rows`, `detail`), its
  *selection mode*, and its *runtime selection set* (`selected_row_ids`). The Hub
  owns all of it; the Display never mutates it locally.
- **Display-local:** the ImGui paint calls, and *continuous in-flight view state*
  — mid-type filter text, the combo-filter choice, scroll offset, and the current
  sort column/direction. These stay on the Display, keyed in `WidgetState`, and a
  whole-UI resend never clobbers them.

A user selection gesture crosses *back* as a `RemoteEventHandlerInvocation` whose
`value` carries the **full new set** of selected `row_id`s (a `list[str]`) — one
event per gesture, even when a range or box gesture toggles many rows at once.

## 2. The exemplar mapping

### 2.1 Interactive leaf with Hub-authoritative selection — `checkbox`

`checkbox` holds `_value: bool`, declares `RemoteDispatchSpec(ValueChanged, ...)`,
registers a built-in handler that mirrors the new value onto the element, and
re-dispatches on the Hub. The table is the same interactive-leaf shape, but its
authoritative value is a **set** of `row_id`s instead of a bool, and it fires
`RowSelectionChanged` instead of `ValueChanged`; every other step of the D21 loop
is identical.

### 2.2 Discrete selection that names stable sub-part ids — `tab_bar`

`tab_bar` (DES-046) carries `_active_tab: str` naming a stable `tab_id`, seeds it
at decode, reconciles it when the tab set changes, and reports it in
`resolved_props()`. The table's selection is the same machinery generalized from
one id to a set: it names `row_id`s (a row's `key_column` value), reconciles by
**set intersection** with the live rows, and reports the set. This is why the
table is *not* a new authority model — it is `tab_bar`'s Hub-authoritative
discrete selection, set-valued.

### 2.3 A table is a leaf, not a composite

DES-045 is explicit that data sub-parts are **not** promoted to elements: "a
`table` with 10 000 rows must not mint 10 000 elements." So the table has **no
child Elements**: `_children()` returns `()`, `child_elements()` returns `()`. It
paints its rows itself in `_paint_widget`, as `TreeElement` paints nested node
data with no child Elements. The table registers as a `LeafKindSpec` (like `tree`,
`checkbox`, `selectable`), not a `ContainerKindSpec`. Its detail panel is
data-driven, not child elements.

The one line: **a `table` is a `tree`-shaped data leaf (it paints structured
data, no child elements) that is also `checkbox`-interactive (a Hub-authoritative
selection), and that selection is `tab_bar`-shaped (stable sub-part ids,
reconciled on structural change) — generalized from one id to a set.**

## 3. The interaction the table fires

One new typed event, `RowSelectionChanged`, a frozen-slots dataclass carrying the
three identifying fields plus its payload — the full new selection set. It lands
in a new `domain/selection_interaction.py`, not in `container_interaction.py`, for
two reasons: `container_interaction.py` already holds three classes (`TabChanged`,
`HeaderToggled`, `ModalClosed`), so a fourth exceeds the PY-OO-2 3-class cap; and
a table is a leaf, not a container, so a data-widget selection is not a *container*
interaction.

- **`RowSelectionChanged`** — payload `row_ids: tuple[str, ...]` (the full set of
  selected row ids after the gesture, ordered by selection recency so the last is
  the anchor). `EventKind` discriminator `"row_selection_changed"`.

Carrying the **full set** (not a per-row toggle) is deliberate: a shift-range or
box gesture changes many rows in one act, so one absolute event per gesture is
both correct and DES-047-shaped (absolute, not a delta). Single-select is the
length-≤1 case. The `EventKind` Literal (`interaction.py:26`) extends to add
`"row_selection_changed"`. The table declares its spec, mirroring `checkbox.py:117`:

```python
def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
    return (RemoteDispatchSpec(RowSelectionChanged, self.id, "row_selection_changed"),)
```

The `RemoteEventHandlerInvocation.value` is already `Any`, so a `list[str]`
crosses with no message-schema change; only the dispatch branches that read
`value` grow.

### The full D21 loop (identical in shape to `tab_bar`)

1. **Built-in state-sync handler registered at decode.** `JsonTableDecoder`
   registers a serializable `_UpdateSelectionHandler(elem)` for
   `RowSelectionChanged`, whose `__call__` runs
   `elem.apply_patch({"selected_row_ids": list(event.row_ids)})`. The handler is a
   small class defined **inside `table_codec.py`** beside the decoder — the exact
   shape of `_UpdateActiveTabHandler` in `tab_bar_codec.py:37` and
   `_UpdateOpenHandler` in `collapsing_header_codec.py`. (It is *not* the
   field-parameterised `ApplyPatchOnChange` that `checkbox`/`selectable` use —
   that reads `event.value`; `RowSelectionChanged` is a distinct `TabChanged`-shaped
   event carrying a set.)
2. **Display wraps the bucket.** After receiving the replica,
   `wrap_handlers_for_remote` finds the `RowSelectionChanged` bucket and collapses
   it into one remote-dispatch group; the Display copy never runs the real state
   update.
3. **User selects rows.** `ImGuiTableRenderer` (via `begin_multi_select` /
   `end_multi_select`) resolves ImGui's selection requests to the new `row_id` set,
   sees it differs from `elem.selected_row_ids`, constructs
   `RowSelectionChanged(..., row_ids=<new set>)`, and calls `elem.fire(event)`.
4. **`fire` sends one remote invocation** —
   `RemoteEventHandlerInvocation(element_id, action=id,
   event_kind="row_selection_changed", value=<list of row_ids>)`.
   `RemoteDispatchGroup.__call__` grows one branch:
   `RowSelectionChanged → value = list(event.row_ids)`.
5. **Hub re-dispatches on its authoritative copy.** The Hub interaction dispatch
   (`domain/hub/clients.py`) grows one branch: `"row_selection_changed" →
   RowSelectionChanged(..., row_ids=tuple(value))`, fires it on the Hub's copy,
   the built-in handler runs `apply_patch({"selected_row_ids": [...]})`, updating
   the authoritative selection. The in-process `Display._build_event` grows the
   same branch.
6. **Hub re-pushes the whole scene.** The re-pushed table carries the new
   `selected_row_ids`; the Display replaces its replica; the detail panel resolves
   to the anchor row.

### The agent-drive (write) path

Because the selection set is a field the Hub owns, the agent drives it by
`apply_patch({"selected_row_ids": ["lux-i3ag", "lux-4n5n"]})` (or a fresh
`show()`) followed by the Hub's re-push. The ImGui adapter *honours*
`elem.selected_row_ids` each frame (syncs its Display-local selection storage from
the authoritative set), not merely reads ImGui's local gesture state — otherwise
an agent-driven change would be ignored. The "last honoured set" is Display-local
*bookkeeping* in `WidgetState`, keyed by the current scene, distinguishing a fresh
Hub write (honour it) from a user gesture (fire `row_selection_changed`) — the
discipline the tab_bar adapter follows (`simple-composites-design.md` §4.7).

### Reconciliation on structural change — set intersection

When a re-push changes the row *set*, the Hub keeps `selected_row_ids` valid by
intersecting with the live row ids, preserving selection order:

- **Rows added.** Every selected id still names a live row → the set is unchanged.
- **Selected rows removed.** The removed ids drop out; the remaining selection
  survives in order. (An index-based selection would have silently shifted — the
  DES-045 payoff, now for a set.)
- **A cell in a selected row changes** (its `key_column` value unchanged) →
  selection unchanged, because the id is the key value, not the row contents.
- **The selection becomes empty and a `detail` panel is present** → the anchor is
  seeded to the first row's key (the legacy auto-select-first behavior,
  `table_renderer.py:112`, generalized: a detail panel always wants something to
  show).

Reconciliation lives on the element (in the `_set_rows` patch setter and at
decode), delegating to `TableSelectionModel.reconcile`. The invariant `validate()`
asserts: **every id in `selected_row_ids` names a live row, and (mode `single`)
the set has at most one member, and (mode `none`) it is empty.**

### Detail-panel binding under multi-select

The detail panel shows one row. Under multi-select it binds to the **anchor** —
the last-selected row (`selected_row_ids` is ordered by recency, so the anchor is
its last element). This matches how file browsers and IDEs show the detail of the
item you most recently clicked within a multi-selection. In single mode the anchor
is the one selected row; with an empty selection and a detail present, the anchor
is the seeded first row. The panel resolves anchor `row_id` → current row index →
`detail[index]` (the detail arrays stay parallel to `rows`).

## 4. Scope-bound sub-questions (answered)

### ImGui multi-select capability check (Decision 2)

The operator asked, explicitly, whether ImGui limits multi-select. Verified
against the installed `imgui-bundle` **1.92.8** (`uv run --extra display`):

| Capability | Present? | Symbol |
|---|---|---|
| Multi-select scope | yes | `imgui.begin_multi_select` / `end_multi_select`, `MultiSelectIO` |
| Single-select via the same API | yes | `MultiSelectFlags_.single_select` |
| Per-item selection tagging | yes | `set_next_item_selection_user_data` |
| Range (shift) + box select | yes | `MultiSelectFlags_.box_select1d` / `box_select2d`; range requests in the IO |
| Clear-on-escape, no-select-all, etc. | yes | `MultiSelectFlags_` |
| Row selectable spanning columns | yes | `SelectableFlags_.span_all_columns` |
| Selection storage helper | yes | `SelectionBasicStorage`, `SelectionExternalStorage` |

**No functional gap.** Single, multi, ctrl-toggle, shift-range, box-select,
select-all, and clear-on-escape are all native; single vs multi is the
`single_select` flag — exactly the framework-standard shape the operator named.

**The one honest constraint.** ImGui identifies a selected item by an integer
`SelectionUserData` (int64), not by our string `row_id`. So the renderer tags
each row's selectable with its **current-display-order index** via
`set_next_item_selection_user_data(index)`, applies ImGui's SetRange / SetAll /
Clear requests against a Display-local index set, and translates the changed
indices → `row_id`s (through the current display order) before firing
`RowSelectionChanged`. This translation is Display-local and total; it imposes no
limit. The authoritative state stays the string `row_id` set — stable across
reorder — and the index mapping is recomputed each frame from the current display
order (so it composes correctly with Display-local sort and filter).

### Legacy feature carry-over

| Legacy feature | Where it lands |
|---|---|
| Filter definitions (`filters`, search/combo) | **Element field** — unchanged. |
| Filter *runtime* values (typed text, chosen combo) | **Display-local** — `WidgetState`; continuous input (DES-046). |
| Manual pagination | **Not carried over** — native scroll (Decision 4); pagination is a possible later additive layer, not closed. |
| `flags: list[str]` (`borders`, `row_bg`, `resizable`, `sortable`) | **Element field, retyped** — a `TableFlags` value object decoded from the wire list (no wire change), killing the `list[str]`-with-a-comment. |
| `copy_id` flag | **Folded into `TableFlags`**; copy-on-select is Display-local convenience. |
| Column sort | **Display-local, made real** (Decision 5) — was dead; the migration reads `table_get_sort_specs()` and reorders the display rows. |
| Row selection | **Hub-authoritative set** (`selected_row_ids` + `selection_mode`) — the migration's core change. |
| Detail panel (`detail`) | **Element field**, unchanged as data; resolved by the anchor `row_id` → row index → `detail[index]`. |

### Column sort — the reality check (Decision 5)

Stated once more plainly, because the operator doubted it works: **sort does
nothing today.** `table_renderer.py:409` maps `sortable` to the ImGui table flag
and there is no `table_get_sort_specs()` call and no reordering in the whole
renderer — the header shows sort arrows that never sort. The migration makes it
real, Display-local: read the sort spec each frame, stably reorder the displayed
rows, leave the authoritative order and the selection (row_id-keyed) untouched.

### The `TableSelectionModel` / private-model split

A private `TableSelectionModel` owns `selection_mode`, `selected_row_ids`, the
anchor, the select/reconcile verbs, and the single/multi/none cardinality logic —
mirroring `ModalModel` (visibility + dismiss). Two reasons over inlining it on the
element: (1) `table.py` is already at the class-count and size ceiling
(`TableFilter`, `TableDetail`, `TableElement` = 3 classes, 263 lines; PY-OO-2 caps
at 3 classes / 300 lines), so `TableFilter` and `TableDetail` move to their own
modules regardless and the selection cluster wants a home; (2) the model localizes
the mode logic — single/multi/none live in one place, not spread across the
element. `TableElement` composes the model (PY-IC-1), it does not inherit it.

### How a 10 000-row table crosses the wire under whole-UI resend

Per the no-premature-diff-protocol rule in `target.md`:

- **Small table (~50 rows × 5 columns) with a detail panel:** ≈ 20 KB total scene.
  A re-push over the local Unix socket is well under 1 ms; a re-push per selection
  gesture is imperceptible.
- **10 000 rows × 5 columns, ~15 chars/cell:** ≈ 0.8 MB of cell text, ≈ 1 MB JSON.
  Local re-push (serialize + transfer + deserialize) is single-digit to low-tens
  of ms — above one 60 fps frame at the large end, but a *one-off reaction to a
  gesture*, not a per-frame cost, and ImGui's clipper still renders only the ~30
  visible rows. The selection set itself is small even for a large multi-select
  (1 000 selected `row_id`s ≈ 10 KB).
- **Conclusion (v1, local only):** no diff protocol. Even a 10 000-row re-push is
  a one-off gesture reaction in the tens-of-ms range locally, under the interactive
  bar, never on the per-frame path (`target.md`: no diff protocol until a real
  performance problem appears).
- **Where it would bite, and the bounded answer:** a *remote* Hub/Display with a
  large table — ~1 MB per gesture over the network (~80 ms at 100 Mbps). The
  bounded fix exists in the DES-047 vocabulary: a selection change is a single
  `SetProperty(selected_row_ids)`, one field, so a future remote optimization
  re-pushes just that property. Deferred v2-remote optimization, out of scope for
  v1.

### Geometry capture — window-like or leaf?

**Leaf, and automatic.** The table registers as a `LeafKindSpec` and its renderer
subclasses `LeafRenderer`, whose `paint()` wraps the widget in the geometry
`measuring` group that records the leaf's whole rect (`display/renderers/imgui/leaf.py`).
The table is inline content within its frame; unlike `window` / `modal` / `dialog`
it owns no draggable rect, so the window/modal/dialog geometry work does not apply
— the leaf measuring group captures the table's bounding rect with no
table-specific code.

## 5. Fork, don't mix

Per DES-041 decision 2, the new ABC class takes the canonical name; the legacy
dataclass is renamed out of the way, as `GroupElement` → `LegacyGroupElement`
(PR #240):

- `protocol/elements/table.py` — `TableElement` → `LegacyTableElement` (class,
  `__all__`, `register_codecs`), keeping its dataclass shape.
- `display/table_renderer.py` — the legacy renderer is retained for
  `LegacyTableElement` until B7 deletes the legacy path. A `table` is a leaf, so
  the all-ABC-gate / legacy-forcing rules for *containers* do not apply — there is
  no child subtree to force. A table dict decodes to the ABC `TableElement`
  whenever it is registered on the leaf path; the factory fork branch routes it.

The beads smoke test needs no code change: `src/punt_lux/apps/beads.py` and the
`lux:beads` skill build the table through the decode path, and the factory routes
the all-scalar table dict to the ABC `TableElement` once it is registered. Its
rows carry a unique id in column 0, so `key_column` default 0 gives it
single-select automatically (see the decode default below).

## 6. The write set

Created / renamed / amended by structure, not predetermined to existing files.
PY-OO-2 (≤ 300 lines, ≤ 3 classes / module) is noted where a split is planned.

**New:**

- `src/punt_lux/protocol/elements/table.py` — the ABC `TableElement` (canonical
  name) composing `TableSelectionModel`. Overrides `id`, `kind`, `_children()`
  (returns `()`), `validate()`, `_remote_dispatch_specs()`, `resolved_props()`;
  setters `_set_rows` (calls reconcile), `_set_columns`, `_set_selected_row_ids`,
  `_set_selection_mode`; resolves `key_column` (int or name) to an index; keeps
  `to_dict` / `from_dict` delegators.
- `src/punt_lux/protocol/elements/table_selection_model.py` —
  `TableSelectionModel` (private): `_mode` (`Literal["none","single","multi"]`),
  the ordered `_selected` tuple, the `anchor`, `apply` / `reconcile` verbs, and
  the single/multi/none cardinality normalization.
- `src/punt_lux/protocol/elements/table_flags.py` — `TableFlags` frozen-slots
  value object (`borders`, `row_bg`, `resizable`, `sortable`, `copy_id`),
  `from_wire(list[str])` / `to_wire() -> list[str]`.
- `src/punt_lux/protocol/elements/table_filter.py` — `TableFilter` moved out.
- `src/punt_lux/protocol/elements/table_detail.py` — `TableDetail` moved out.
- `src/punt_lux/protocol/elements/table_codec.py` — `JsonTableEncoder` /
  `JsonTableDecoder` **and the built-in `_UpdateSelectionHandler`** (a small
  serializable class beside the decoder, mirroring `_UpdateActiveTabHandler` in
  `tab_bar_codec.py:37`). The decoder registers the handler via
  `elem.add_handler(RowSelectionChanged, _UpdateSelectionHandler(elem))` before
  wire handlers; resolves `selection_mode` (omitted → `single` when a `detail` is
  present or `copy_id` set, else `none` — preserving legacy selectability while
  making the mode explicit); seeds the anchor to the first row's key when a
  `detail` is present and the wire omits a selection.
- `src/punt_lux/domain/selection_interaction.py` — `RowSelectionChanged`
  (payload `row_ids: tuple[str, ...]`). A new module, not `container_interaction.py`
  (that is at the 3-class cap, and a table is a leaf, not a container).
- `src/punt_lux/display/renderers/imgui/table.py` — `ImGuiTableRenderer`
  (`@final`, subclasses `LeafRenderer[TableElement]`): paints filters, the
  scrollable row region (native scroll + list clipper), the multi-select flow
  (`begin/end_multi_select`, `single_select` in single mode, index↔row_id
  translation), Display-local sort (`table_get_sort_specs()` + stable reorder of
  the display list), and the detail panel bound to the anchor; honours
  `elem.selected_row_ids`; fires `RowSelectionChanged` on a user gesture; keeps
  filter/scroll/sort Display-local in `WidgetState`.
- `tests/test_table_element.py` — Levels 1–5 + validation (§8).
- `tests/e2e/scenario.py` — an interactive multi-select Scenario + a
  reconcile-on-reorder Scenario.

**Amended:**

- `src/punt_lux/domain/interaction.py` — extend `EventKind` with
  `"row_selection_changed"`.
- `src/punt_lux/domain/handlers/remote_dispatch.py` —
  `RemoteDispatchGroup.__call__` adds `RowSelectionChanged → value =
  list(event.row_ids)`.
- `src/punt_lux/domain/hub/clients.py` — the Hub interaction dispatch adds
  `event_kind == "row_selection_changed" → RowSelectionChanged(..., row_ids=tuple(value))`.
- `src/punt_lux/domain/display.py` — `Display._build_event` adds the same branch.
- `src/punt_lux/protocol/elements/abc_leaf_kinds.py` — a `LeafKindSpec` entry for
  `table` with `handler_builder` for the selection handler.
- `src/punt_lux/protocol/element_factory.py` — a `_table_decoder` field and the
  `element_from_dict` fork branch (ABC vs `LegacyTableElement`).
- `src/punt_lux/protocol/elements/__init__.py` — the `Element` union gains ABC
  `TableElement` + `LegacyTableElement`; `_element_to_dict` adds ABC
  `TableElement` to the per-kind-encoder tuple.
- `src/punt_lux/protocol/encoder_factory.py` — the `TableElement` encode entry.
- `src/punt_lux/display/renderers/imgui/factory.py` — `(TableElement,
  ImGuiTableRenderer)` in `_DISPATCH`.
- `.oo-baseline.json`, `.oo-audit.jsonl` — staged with each commit.

Legacy deletion (`LegacyTableElement`, `table_renderer.py`) is **B7**, not this
migration.

## 7. Type sketches (recommended shape)

```python
# domain/selection_interaction.py (new module) — mirrors TabChanged, set-valued
@dataclass(frozen=True, slots=True, init=False)
class RowSelectionChanged:
    """A typed selection-change event for a table. Carries the full new set of
    selected row ids, ordered by selection recency (last = anchor)."""

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
    """The table's private selection state and the cardinality logic.

    ``none`` is a display-only table (no selection, no key-column constraint);
    ``single`` keeps at most one id; ``multi`` holds a set. ``_selected`` is
    ordered by selection recency so ``anchor`` (its last element) is the row the
    detail panel binds to. Widening/narrowing the mode is a change here, not on
    the element.
    """

    _mode: SelectionMode
    _selected: tuple[str, ...]  # ordered by recency; anchor is the last

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
        """The last-selected id (detail-panel binding), or "" if none."""
        return self._selected[-1] if self._selected else ""

    def apply(self, row_ids: tuple[str, ...]) -> None:
        """Set the selection from a user gesture or an agent drive.

        ``none`` -> always empty; ``single`` -> keep only the last id; ``multi``
        -> the full ordered set (deduplicated, order preserved).
        """

    def reconcile(self, live_ids: tuple[str, ...], *, seed_first: str) -> None:
        """Keep only ids still present (order preserved). If the result is empty
        and a detail is present, seed the anchor to ``seed_first``."""


# protocol/elements/table.py — the ABC leaf (checkbox-interactive, tree-data-shaped)
class TableElement(Element):
    """A data table: a leaf (no child elements) with a Hub-authoritative row
    selection set. tooltip stays str | None — absence is the documented contract."""

    _id: str
    _columns: tuple[str, ...]
    _rows: tuple[tuple[object, ...], ...]
    _flags: TableFlags
    _key_column: int          # resolved from int-or-name at decode
    _filters: tuple[TableFilter, ...]
    _detail: TableDetail | None
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
        """The stable id of a row — the string value of its key column."""
        return str(row[self._key_column])

    def _set_rows(self, value: object) -> None:
        self._rows = PatchField("rows").as_rows(value)
        live = tuple(self._row_id(r) for r in self._rows)
        self._selection.reconcile(live, seed_first=self._first_key())

    def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
        return (RemoteDispatchSpec(RowSelectionChanged, self.id, "row_selection_changed"),)

    def validate(self) -> tuple[ValidationError, ...]:
        """Rows-vs-columns + renderable cells (kept from legacy) always. When the
        table is selectable (mode != "none"): the key column's values are
        non-empty and unique (so a row_id is a stable, unambiguous key), every
        selected id names a live row, mode "single" holds at most one, and the
        key_column name/index resolves. A display-only (mode "none") table has no
        such constraint — a repeated key column is fine. Detail arrays stay
        parallel to rows whenever a detail is present."""

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

## 8. Verify plan — Levels 1–6

Write expected values first; drive the real entry point; assert against live
state. `make check` passes and `.oo-baseline.json` + `.oo-audit.jsonl` are staged
in the same commit.

1. **Level 1 — serialization roundtrip.** Build tables in each mode
   (`none`, `single`, `multi`), with rows carrying a unique key column, filters, a
   detail, and an explicit `selected_row_ids` → `to_dict` → `from_dict` → assert
   equal. Include `key_column` given as a **name** and as an **index**, an empty
   selection, and a table nested in a `group`.
2. **Self-validation (DES-039).**
   - **valid** → `validate()` returns `()`; the tree renders.
   - **malformed (always)** → a ragged row, a non-scalar cell, a detail array
     length ≠ rows, a `key_column` name absent from `columns` or an out-of-range
     index — each returns the error; via `show()`, assert
     `client.show.assert_not_called()`.
   - **malformed (selectable only)** → mode `single`/`multi` with a duplicate or
     empty key value, a `selected_row_id` naming no row, or mode `single` with two
     selected ids — each returns the error.
   - **regression guard (mode `none`)** → a display-only table whose key column
     repeats (a `{status, count}` aggregate) `validate()`s to `()` and renders —
     the case the mode scoping protects.
   - **structural guard** → the DES-039 container-guard test passes (a leaf exposes
     `child_elements() == ()`).
3. **Level 2 — wire roundtrip (ABC pickled path).** Put a multi-select table in a
   `SceneMessage` → serialize → deserialize → assert equal; assert it crossed as a
   `_pickled` entry and its built-in `_UpdateSelectionHandler` survived inside the
   blob.
4. **Level 3 — Hub/Display crossing.** Install the table into `HubDisplay` → push
   → assert an equal replica and that `bind_renderer_factory` rebound the factory.
5. **Level 4 — the harness Scenarios.**
   - **Interactive multi-select** `table_multi_select_progress`: a `multi` table
     beside a display-only `progress`. The injected interaction is a
     `row_selection_changed` carrying two row ids (a range gesture); the built-in
     state-sync sets the Hub `selected_row_ids`, so the dispatch re-push carries
     the mutated set (`PropAfterDispatch(field="selected_row_ids", value=[...])`).
     A wire `handlers` entry publishes `rows_opened`; the agent advances the
     progress — Decision 1's publish path exercised.
   - **Reconcile-on-reorder** `table_reorder_keeps_selection`: select ids `{a, c}`,
     re-push the rows reordered with a row inserted and `b` removed, assert
     `selected_row_ids == (a, c)` (order preserved, survivors kept) — the DES-045
     payoff for a set.
6. **Level 5 — introspection.** Query `inspect_scene`; assert `render_path == "abc"`
   and `resolved_props` reads back `columns`, `row_count`, `selection_mode`,
   `selected_row_ids`, and `anchor_row_id`. After the interactive Scenario, assert
   the reported set reflects the interaction.
7. **Level 6 — live visual confirmation.** `make restart`; render a `multi` table
   through the real `show_table`, and the beads board through `lux:beads` (the
   smoke test). Confirm by eye + `screenshot`: click selects, ctrl-click toggles,
   shift-click range-selects, box-select works; a real column sort reorders rows
   and keeps the selection; filtering and scrolling do not disturb the selection;
   an agent-driven `selected_row_ids` re-push moves the highlight with no user
   gesture. Capture `inspect_scene` + `list_recent_events`; **operator confirms**
   before the kind is called done.

## 9. Report status

Design ratified with the operator's amendments and updated accordingly. No
production code written. The five decisions are recorded as ruled; the design,
type sketches, and verify plan reflect single+multi-select (`selection_mode` +
`selected_row_ids`), the verified ImGui multi-select capability and its one
Display-local constraint, `key_column` as a per-table int-or-name attribute, native
scroll with pagination as a possible later layer, and Display-local sort made real
after confirming it is dead today. Saved to
`docs/architecture/migration/table-design.md`. Implementation dispatches against
this amended design.
