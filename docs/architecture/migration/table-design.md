# Migrating `table` onto the Element-ABC / HubDisplay Path — the Last Data Widget (B6)

**Status:** design + verification plan. No code. The selection-authority
questions the operator must rule on are collected in
[Decisions for the operator](#decisions-for-the-operator) at the top, in
liftable form.
**Type:** migration design (interactive data widget; batch B6, the last real
migration — B7 is deletion).
**Element:** `table` (columns + rows, built-in filters, pagination, row
selection, detail panel).
**Exemplars copied:**

- **`CheckboxElement`** (`protocol/elements/checkbox.py:40`,
  `display/renderers/imgui/checkbox.py`) — the interactive leaf: one
  Hub-authoritative value, a `_remote_dispatch_specs`, a built-in state-sync
  handler, the Display-side wrap, Hub-side re-dispatch, a re-push.
- **`TreeElement`** (registered as a `LeafKindSpec` in
  `abc_leaf_kinds.py`) — the data-bearing leaf: it paints structured, nested
  data with **no child Elements**. A table's rows are data, not elements, so a
  table is a leaf in the same sense (see [§2.3](#23-a-table-is-a-leaf-not-a-composite)).
- **`TabBarElement`** (`simple-composites-design.md`, DES-046) — the
  Hub-authoritative *discrete selection* that references a **stable sub-part id**
  (`tab_id`) and reconciles when the sub-part set changes. The table's row
  selection is the same machinery one level down: a `row_id` instead of a
  `tab_id`.
- **`ModalModel`** (`protocol/elements/modal.py:47`) — the private model that
  owns a cohesive state cluster; the recommended `TableSelectionModel`
  ([§7](#7-type-sketches-recommended-shape)) mirrors it.

**Ground truth:** `docs/architecture/target/{target,ui-model,element-contract}.md`,
[DES-039](../../../DESIGN.md) (self-validating elements),
[DES-041](../../../DESIGN.md) (fork, don't mix; order by testability),
[DES-045](../../../DESIGN.md) (stable sub-element id, never a positional index),
[DES-046](../../../DESIGN.md) (view-state locality: discrete selections are
Hub-authoritative, continuous input is Display-local),
[DES-047](../../../DESIGN.md) (the Hub-authoritative write path), the render
engine (PR #239), and the code cited inline.

---

## Decisions for the operator

Each is a genuine fork with one recommendation. Implementation does not dispatch
until these are ruled on. The settled constraints below the list are **not**
reopened.

**Decision 1 — Does the table carry a business-event publish alongside its
authoritative selection? Recommend YES (option C).** DES-046 already rules the
row selection *itself* is Hub-authoritative element state, which removes the
"event-only, no state" option. The live choice is between (A) selection is pure
Hub state and nothing else, and (C) selection is Hub state *and* an interaction a
client can attach an app handler to (publish `openTicket`, etc.). Recommend C
because it is the established pattern, not a new one: `checkbox` and `selectable`
already carry an optional publish handler on top of their authoritative value,
and `ui-model.md` uses a table row-select publishing `openTicket` as its worked
example. (A) would deliberately strip the table of the app affordance every other
interactive kind has. Cost of C over A is zero when no handler is attached — the
built-in state-sync handler runs alone.

**Decision 2 — Single-select or multi-select for v1? Recommend SINGLE-select.**
The one real consumer (the beads browser, `apps/beads.py` + the `lux:beads`
skill) is a single-selection list with a detail panel — exactly one row is
highlighted and its detail shown. Recommend a single `selected_row_id` for v1,
with the selection state owned by a private `TableSelectionModel`
([§7](#7-type-sketches-recommended-shape)) so widening to multi-select later is an
additive change to that one model plus one wire field, not a redesign. Building
multi-select now adds a set-valued wire field, multi-row reconciliation, and a
detail-panel-vs-multi-selection question with no caller to validate it against.

**Decision 3 — How is a row's stable id sourced? Recommend a `key_column` index,
defaulting to column 0.** DES-045 requires selection to name a stable `row_id`,
never a positional index, and offers "an agent-designated key column or a
synthesized stable key." Three concrete mechanisms:

| Mechanism | Row id is | Fit |
|---|---|---|
| **`key_column: int = 0`** (recommend) | `str(row[key_column])` | The beads table already puts a unique ID in column 0; `copy_id` already treats column 0 as the id. Zero wire growth for the common case. |
| Explicit `row_ids: list[str]` parallel to `rows` | agent-sent, off-screen | Most flexible (id need not be displayed) but adds a parallel-array field and its length invariant, for a case no consumer has. |
| Synthesized hash of the whole row | `hash(tuple(row))` | No agent involvement, but the id *changes when any cell in the row is edited*, so an edit "moves" the selection — the exact reorder-fragility DES-045 removes. |

Recommend `key_column` (default 0). `validate()` enforces that the key column's
values are **non-empty and unique** (so `""` can unambiguously mean "no row
selected", mirroring `tab_bar`'s empty-`active_tab` state and its duplicate-id
check). Reject the hash as the default (fragile under cell edits); defer the
explicit `row_ids` array until a consumer needs an off-screen key.

**Decision 4 — Keep manual pagination, or replace it with native scrolling?
Recommend REPLACE with a native ImGui scroll region (Display-local).** The legacy
renderer paginates in fixed 10-row pages with `<< Prev` / `Next >>` buttons
(`table_renderer.py:286`). Under DES-046 a *paged* selection index is
"discrete, agent-drivable" and would become Hub-authoritative (the paged-`group`
consequence, `simple-composites-design.md` §4.3) — carrying real machinery. The
alternative is to drop manual pagination and render the rows inside a scrollable
child region: ImGui's list clipper draws only the ~30 visible rows regardless of
row count, and scroll offset is *continuous input* → Display-local (DES-046),
never re-pushed. Recommend native scroll: it removes the page-index state
entirely, sidesteps the pagination-vs-selection-vs-reorder interaction, and is
the natural viewport for a data table. Pagination was a pre-scroll workaround.

**Decision 5 — Is column sort view-state or authoritative? Recommend
Display-local view-state (Decision 3 of DES-041).** DES-041 decision 3 lists
"column sort?" as the one open item in the ephemeral-view-state set. Recommend it
stay Display-local: sort is a view transform of how the user looks at the data,
like scroll and filter, and — critically — because selection names a stable
`row_id`, sorting the view never disturbs the selection (that is the whole point
of DES-045). The legacy code already leaves sort to ImGui's internal state and
does not reorder rows itself, so Display-local matches current reality. If
agent-driven sort is wanted in v2 it moves to Hub-authoritative exactly as the
tab selection did; nothing in this design blocks that.

### Settled constraints (not reopened)

- **Row selection is Hub-authoritative** — it crosses the wire, the Hub owns it,
  the agent can drive it, a user click fires an event the Hub records, the Hub
  reconciles it on structural change, and the change is re-pushed (DES-046).
- **Selection references a stable `row_id`, never a positional `row_index`** — the
  legacy `row_index` (`table_renderer.py:165`) is the latent reorder bug this
  migration removes (DES-045).
- **Filter text and scroll offset are Display-local** — continuous in-progress
  input, never re-pushed, a whole-UI resend never clobbers them (DES-046 /
  DES-041 decision 3).
- **Fork, don't mix** — the ABC `TableElement` takes the canonical name; the
  legacy dataclass is renamed `LegacyTableElement` and its renderer retained
  until B7 deletes the legacy path (DES-041).
- **`validate()` rides with the migration** — the table gains its
  component-appropriate `validate()` as it crosses; it already exists on the
  frozen legacy class (`table.py:143`) and moves onto the ABC class, extended
  with the key-column invariant (DES-039).
- **Writes are absolute, id-addressed, idempotent** — an agent-driven selection
  is a `SetProperty` / `apply_patch({"selected_row_id": ...})` on the Hub copy,
  re-pushed whole (DES-047).

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
  `columns`, `rows`, `filters`, `detail`, `flags`, `key_column`, and its built-in
  selection state-sync handler. A top-level ABC element crosses as one pickled
  blob; the built-in handler travels inside it, which is what lets the Display
  wrap the selection interaction for remote dispatch.
- **Hub-authoritative:** the table's *data* (`columns`, `rows`, `detail`) and its
  *runtime selection* (`selected_row_id`). The Hub owns all of it; the Display
  never mutates it locally.
- **Display-local:** the ImGui paint calls, and *continuous in-flight view state*
  — mid-type filter text, the combo-filter choice, scroll offset, column sort.
  These stay on the Display, keyed in `WidgetState`, and a whole-UI resend never
  clobbers them.

The row-select interaction crosses *back* as a `RemoteEventHandlerInvocation`
whose `value` carries the new `row_id` string — the same shape `tab_bar` uses to
carry a `tab_id`.

## 2. The exemplar mapping

### 2.1 Interactive leaf with one Hub-authoritative value — `checkbox`

`checkbox` holds `_value: bool`, declares
`RemoteDispatchSpec(ValueChanged, ...)`, registers a built-in handler that
mirrors the new value onto the element, and re-dispatches on the Hub. The table
holds `selected_row_id` instead of a bool and fires `RowSelected` instead of
`ValueChanged`; every other step of the D21 loop is identical.

### 2.2 Discrete selection that names a stable sub-part id — `tab_bar`

`tab_bar` (DES-046) carries `_active_tab: str` naming a stable `tab_id`, seeds it
at decode, reconciles it when the tab set changes (removed active tab → reset to
the first live tab), and reports it in `resolved_props()`. The table's
`selected_row_id` is the same field one level down — it names a `row_id` (a
row's `key_column` value) instead of a `tab_id`, and reconciles the same way
(selected row gone after a re-push → clear or reset). This is why the table is
*not* a new authority model: it is `tab_bar`'s Hub-authoritative discrete
selection applied to data rows.

### 2.3 A table is a leaf, not a composite

DES-045 is explicit that data sub-parts are **not** promoted to elements: "a
`table` with 10 000 rows must not mint 10 000 elements." So the table has **no
child Elements**: `_children()` returns `()`, `child_elements()` returns `()`.
It paints its rows itself in `_paint_widget`, exactly as `TreeElement` paints
nested node data with no child Elements. The table therefore registers as a
`LeafKindSpec` (like `tree`, `checkbox`, `selectable`), not a `ContainerKindSpec`.
Its detail panel is likewise data-driven, not child elements.

The one line: **a `table` is a `tree`-shaped data leaf (it paints structured
data, no child elements) that is also `checkbox`-interactive (one
Hub-authoritative selection value), and that selection is `tab_bar`-shaped (a
stable sub-part id, reconciled on structural change).**

## 3. The interaction the table fires

One new typed event (`domain/container_interaction.py`, beside `TabChanged`),
a frozen-slots dataclass carrying the three identifying fields plus its payload,
exactly like `TabChanged`:

- **`RowSelected`** — payload `row_id: str` (the newly-selected row's stable id).
  `EventKind` discriminator `"row_selected"`.

The `EventKind` Literal (`interaction.py:26`) extends to add `"row_selected"`.
The table declares its spec, mirroring `checkbox.py:117` / the tab_bar design:

```python
def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
    return (RemoteDispatchSpec(RowSelected, self.id, "row_selected"),)
```

The action is the element `id` — one selection interaction per table, so the id
is the natural bucket key (the default `button` uses). The wire message
`RemoteEventHandlerInvocation.value` is already `Any`, so a `str` row id crosses
with no message-schema change; only the dispatch branches that read `value` grow.

### The full D21 loop (identical in shape to `tab_bar`)

1. **Built-in state-sync handler registered at decode.** `JsonTableDecoder`
   registers a serializable `_UpdateSelectedRowHandler(elem)` for `RowSelected`,
   whose `__call__` runs `elem.apply_patch({"selected_row_id": event.row_id})` —
   the same role `_UpdateValueHandler` plays for `checkbox`.
2. **Display wraps the bucket.** After receiving the replica, the Display's
   `wrap_handlers_for_remote` finds the `RowSelected` bucket and collapses it into
   one remote-dispatch group; the Display copy never runs the real state update.
3. **User clicks a row.** `ImGuiTableRenderer` detects the clicked row's `row_id`
   differs from `elem.selected_row_id`, constructs `RowSelected(..., row_id=...)`,
   and calls `elem.fire(event)`.
4. **`fire` sends one remote invocation** — `RemoteEventHandlerInvocation(
   element_id, action=id, event_kind="row_selected", value=<row_id>)`.
   `RemoteDispatchGroup.__call__` grows one branch: `RowSelected → value =
   event.row_id`.
5. **Hub re-dispatches on its authoritative copy.** The Hub interaction dispatch
   (`domain/hub/clients.py`) grows one branch: `"row_selected" → RowSelected(...,
   row_id=value)`, fires it on the Hub's copy, the built-in handler runs
   `apply_patch({"selected_row_id": row_id})`, updating the authoritative
   selection. The in-process `Display._build_event` grows the same branch.
6. **Hub re-pushes the whole scene.** The re-pushed table carries the new
   `selected_row_id`; the Display replaces its replica; the detail panel now
   resolves to the selected row.

### The agent-drive (write) path

Because the selection is a field the Hub owns, the agent drives it the same way
it drives any field: `apply_patch({"selected_row_id": "lux-i3ag"})` (or a fresh
`show()`) followed by the Hub's re-push. The ImGui adapter must *honour*
`elem.selected_row_id` each frame (highlight the row whose key matches), not
merely read ImGui's local click state — otherwise an agent-driven selection would
be ignored. The "last honoured id" is Display-local *bookkeeping* in
`WidgetState`, keyed by the current scene, distinguishing a fresh Hub write
(honour it) from a user click (fire `row_selected`) — the discipline the tab_bar
adapter follows (`simple-composites-design.md` §4.7).

### Reconciliation on structural change

When a re-push changes the row *set*, the Hub keeps `selected_row_id` valid — the
`tab_bar` membership check one level down:

- **A row is added.** `selected_row_id` still names a live row → unchanged. (An
  index would have silently shifted; a `row_id` does not — the direct payoff of
  DES-045.)
- **A row is removed.** If it was not the selected row → unchanged. If it *was*,
  the Hub resets `selected_row_id` to `""` (no selection) — or, when a `detail`
  panel is present, to the first remaining row's key, matching the legacy
  auto-select-first behavior (`table_renderer.py:112`).
- **A cell in the selected row changes** (but its `key_column` value does not) →
  selection unchanged, because the id is the key value, not the row contents.

Reconciliation lives on the element, invoked whenever the rows are replaced —
inside the `_set_rows` patch setter and at decode (seeding `selected_row_id` to
the first row's key when a `detail` is present and the wire omits a selection).
The invariant `validate()` asserts: **`selected_row_id` is `""` or names a live
row, always.**

## 4. Scope-bound sub-questions (answered)

**Which legacy features carry over as element fields vs stay renderer-internal.**

| Legacy feature | Where it lands |
|---|---|
| Filter definitions (`filters: list[TableFilter]`, search/combo) | **Element field** — already is; unchanged. |
| Filter *runtime* values (typed search text, chosen combo item) | **Display-local** — `WidgetState`, unchanged; continuous input (DES-046). |
| Pagination / paged layout | **Removed** — replaced by native scroll (Decision 4); scroll offset is Display-local. |
| `flags: list[str]` (`borders`, `row_bg`, `resizable`, `sortable`) | **Element field, retyped** — a `TableFlags` value object decoded from the wire list (no wire change), killing the `list[str]` violation of the "no str with a comment listing values" rule. |
| `copy_id` flag (copy the key to the clipboard on select) | **Element field (retyped into `TableFlags`)**; the copy itself is Display-local convenience behavior on select. |
| Column sort | **Display-local view-state** (Decision 5). |
| Row selection | **Hub-authoritative element state** (`selected_row_id`) — the migration's core change. |
| Detail panel (`detail: TableDetail`, fields/rows/body) | **Element field**, unchanged as data; resolved by `row_id` → row index → `detail[index]` instead of by positional `row_index`. |

**The `TableModel` / private-model split.** Recommend a private
`TableSelectionModel` owning `selected_row_id`, the `select(row_id)` verb, and
the reconciliation, mirroring `ModalModel` (visibility + dismiss). Two reasons
over keeping it inline on the element as `tab_bar` did: (1) the current `table.py`
is already at the class-count and size ceiling (`TableFilter`, `TableDetail`,
`TableElement` = 3 classes, 263 lines; PY-OO-2 caps at 3 classes / 300 lines), so
`TableFilter` and `TableDetail` move to their own modules regardless and the
selection cluster wants a home; (2) the model localizes the single-vs-multi
cardinality decision (Decision 2) — widening to multi-select changes the model
internally, not the element. `TableElement` composes the model (PY-IC-1), it does
not inherit it.

**How a 10 000-row table crosses the wire under whole-UI resend.** State the math
per the no-premature-diff-protocol rule in `target.md`:

- **Beads-typical (~50 rows × 5 columns), with a detail panel:** rows ≈ 4 KB,
  detail ≈ 15 KB, total scene ≈ 20 KB. A re-push over the local Unix socket
  (pickle + write + read) is well under 1 ms. A re-push *per selection click* is
  imperceptible.
- **10 000 rows × 5 columns, ~15 chars/cell:** ≈ 0.8 MB of cell text, ≈ 1 MB JSON
  without large detail bodies. Local re-push (serialize + transfer + deserialize)
  is single-digit to low-tens of ms — above one 60 fps frame at the large end,
  but this is a *one-off reaction to a click*, not a per-frame cost, and ImGui's
  clipper still renders only the ~30 visible rows.
- **Conclusion (v1, local only):** no diff protocol. Even a 10 000-row re-push is
  a one-off click reaction in the tens-of-ms range locally, under the interactive
  bar and never on the per-frame path. Do **not** build a delta protocol now
  (`target.md`: "Lux does not need a diff protocol until a real performance
  problem appears").
- **Where it would bite, and the bounded answer:** a *remote* Hub/Display with a
  large table — ~1 MB per selection click over the network (~80 ms at 100 Mbps)
  before the highlight settles. The bounded fix already exists in the DES-047
  vocabulary: a selection change is a single `SetProperty(selected_row_id)`, one
  field, so a future remote optimization re-pushes just that property instead of
  the whole root. This is a deferred v2-remote optimization (the same class as
  the tab_bar network-hop note), explicitly out of scope for v1.

**Geometry capture — window-like or leaf?** **Leaf, and it is automatic.** The
table registers as a `LeafKindSpec` and its renderer subclasses `LeafRenderer`,
whose `paint()` wraps the widget in the geometry `measuring` group that records
the leaf's whole rect when the group closes (`display/renderers/imgui/leaf.py`).
The table is inline content within its enclosing frame; unlike `window` / `modal`
/ `dialog` it owns no draggable rect of its own, so the recent window/modal/dialog
geometry work does not apply — the leaf measuring group captures the table's
bounding rect with no table-specific code.

**What happens to sort.** Display-local view-state (Decision 5). Because selection
is by `row_id`, sorting the view never moves the selection; the sort column and
direction live Display-side and are never re-pushed.

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

The beads consumer needs **no change**: `apps/beads.py` and the `lux:beads` skill
both build the table through the decode path, and the factory routes the
all-scalar table dict to the ABC `TableElement` once it is registered. The beads
rows already carry a unique ID in column 0, so `key_column` default 0 works
unchanged.

## 6. The write set

Created / renamed / amended by structure, not predetermined to existing files.
PY-OO-2 (≤ 300 lines, ≤ 3 classes / module) is noted where a split is planned;
every module follows the element/codec split precedent.

**New:**

- `src/punt_lux/protocol/elements/table.py` — the ABC `TableElement` (canonical
  name) composing `TableSelectionModel`. Overrides `id`, `kind`, `_children()`
  (returns `()`), `validate()`, `_remote_dispatch_specs()`, `resolved_props()`;
  setters `_set_rows` (calls reconcile), `_set_columns`, `_set_selected_row_id`;
  keeps `to_dict` / `from_dict` delegators.
- `src/punt_lux/protocol/elements/table_selection_model.py` —
  `TableSelectionModel` (private; `selected_row_id`, `select`, `reconcile`; the
  single-vs-multi cardinality lives here).
- `src/punt_lux/protocol/elements/table_flags.py` — `TableFlags`
  frozen-slots value object (`borders`, `row_bg`, `resizable`, `sortable`,
  `copy_id` booleans), `from_wire(list[str])` / `to_wire() -> list[str]`.
- `src/punt_lux/protocol/elements/table_filter.py` — `TableFilter` moved out of
  the legacy module (a `type: Literal["search", "combo"]` value class; unchanged).
- `src/punt_lux/protocol/elements/table_detail.py` — `TableDetail` moved out.
- `src/punt_lux/protocol/elements/table_codec.py` — `JsonTableEncoder` /
  `JsonTableDecoder` (registers the built-in `_UpdateSelectedRowHandler` before
  wire handlers; seeds `selected_row_id` to the first row's key when a `detail` is
  present and the wire omits a selection).
- `src/punt_lux/protocol/standalone_table_handler.py` — the serializable
  `_UpdateSelectedRowHandler` + a `noop` factory, parallel to
  `standalone_checkbox_handler.py`.
- `src/punt_lux/display/renderers/imgui/table.py` — `ImGuiTableRenderer`
  (`@final`, subclasses `LeafRenderer[TableElement]`): paints filters, the
  scrollable row region (native scroll, list clipper), and the detail panel;
  honours `elem.selected_row_id`; fires `RowSelected` on a user click; keeps
  filter/scroll/sort Display-local in `WidgetState` keyed by the current scene.
  Much of the legacy `table_renderer.py` body (filter widgets, column weights,
  detail grid) is reused, minus pagination and the `row_index` selection.
- `tests/test_table_element.py` — Levels 1–5 + validation (§8).
- `tests/e2e/scenario.py` — an interactive `row_selected` Scenario + a
  reconcile-on-reorder Scenario.

**Amended:**

- `src/punt_lux/domain/container_interaction.py` — add `RowSelected`
  (payload `row_id: str`); if the module would exceed 3 classes, split the
  selection events into a sibling module.
- `src/punt_lux/domain/interaction.py` — extend `EventKind` with
  `"row_selected"`.
- `src/punt_lux/domain/handlers/remote_dispatch.py` —
  `RemoteDispatchGroup.__call__` adds `RowSelected → value = event.row_id`.
- `src/punt_lux/domain/hub/clients.py` — the Hub interaction dispatch adds
  `event_kind == "row_selected" → RowSelected(..., row_id=value)`.
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
migration (fork, don't mix).

## 7. Type sketches (recommended shape)

```python
# domain/container_interaction.py — mirrors TabChanged exactly
@dataclass(frozen=True, slots=True, init=False)
class RowSelected:
    """A typed row-selection event for a table. Carries the row's stable id."""

    scene_id: SceneId
    element_id: ElementId
    owner_id: ClientId
    row_id: str
    kind: ClassVar[Literal["row_selected"]] = "row_selected"
    # __new__ / from_wire as TabChanged (object.__setattr__ over the slots)


# protocol/elements/table_flags.py — kills the list[str]-with-a-comment
@dataclass(frozen=True, slots=True)
class TableFlags:
    """The table's render flags as a typed value object."""

    borders: bool = True
    row_bg: bool = True
    resizable: bool = False
    sortable: bool = False
    copy_id: bool = False

    @classmethod
    def from_wire(cls, flags: list[str]) -> Self: ...
    def to_wire(self) -> list[str]: ...


# protocol/elements/table_selection_model.py — private, mirrors ModalModel
class TableSelectionModel:
    """The table's private selection state and the select/reconcile verbs.

    Owns single-select today; widening to multi-select is a change here, not on
    the element. "" means no row selected (validate() forbids an empty key value,
    so "" is unambiguous).
    """

    _selected_row_id: str

    def __new__(cls, *, selected_row_id: str = "") -> Self: ...

    @property
    def selected_row_id(self) -> str: ...

    def select(self, row_id: str) -> None:
        """Record the user's / agent's selection."""
        self._selected_row_id = row_id

    def reconcile(self, live_ids: tuple[str, ...], *, first_on_loss: str) -> None:
        """Keep the selection naming a live row after the row set changes.

        A selection still present is kept; a lost selection resets to
        ``first_on_loss`` (the first row's key when a detail is present, else "").
        """
        if self._selected_row_id in live_ids:
            return
        self._selected_row_id = first_on_loss


# protocol/elements/table.py — the ABC leaf (checkbox-interactive, tree-data-shaped)
class TableElement(Element):
    """A data table: a leaf (no child elements) with a Hub-authoritative row
    selection. tooltip stays str | None — absence is the documented contract."""

    _id: str
    _columns: tuple[str, ...]
    _rows: tuple[tuple[object, ...], ...]
    _flags: TableFlags
    _key_column: int
    _filters: tuple[TableFilter, ...]
    _detail: TableDetail | None
    _selection: TableSelectionModel
    _tooltip: str | None
    _kind: Literal["table"]

    @property
    def selected_row_id(self) -> str:
        return self._selection.selected_row_id

    def _row_id(self, row: tuple[object, ...]) -> str:
        """The stable id of a row — the string value of its key column."""
        return str(row[self._key_column])

    def _set_rows(self, value: object) -> None:
        self._rows = PatchField("rows").as_rows(value)
        live = tuple(self._row_id(r) for r in self._rows)
        self._selection.reconcile(live, first_on_loss=self._first_on_loss())

    def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
        return (RemoteDispatchSpec(RowSelected, self.id, "row_selected"),)

    def validate(self) -> tuple[ValidationError, ...]:
        """Rows-vs-columns + renderable cells (kept from legacy), plus:
        the key column's values are non-empty and unique (so a row_id is a
        stable, unambiguous key and "" cleanly means no selection); the detail
        arrays stay parallel to rows; selected_row_id names a live row or ""."""

    def resolved_props(self) -> Mapping[str, object]:
        return {
            "columns": list(self._columns),
            "row_count": len(self._rows),
            "selected_row_id": self.selected_row_id,
            "key_column": self._key_column,
            "tooltip": self._tooltip,
        }
```

## 8. Verify plan — Levels 1–6

Write expected values first; drive the real entry point; assert against live
state. `make check` passes and `.oo-baseline.json` + `.oo-audit.jsonl` are staged
in the same commit.

1. **Level 1 — serialization roundtrip.** Build a `table` (columns, rows with a
   unique column 0, filters, a detail, an explicit `selected_row_id`) → `to_dict`
   → `from_dict` → assert equal. Include a table with no selection
   (`selected_row_id == ""`) and one nested in a `group`.
2. **Self-validation (DES-039).**
   - **valid** → `validate()` returns `()`; the tree renders.
   - **malformed** → a ragged row, a non-scalar cell (list/dict), a duplicate or
     empty key-column value, a detail array whose length ≠ rows, a
     `selected_row_id` naming no row — each returns the component-appropriate
     error; driven through `show()`, assert `client.show.assert_not_called()`.
   - **structural guard** → the DES-039 container-guard test passes with the ABC
     class in the union (a leaf exposes `child_elements() == ()`).
3. **Level 2 — wire roundtrip (ABC pickled path).** Put the table in a
   `SceneMessage` → serialize → deserialize → assert equal; assert it crossed as a
   `_pickled` entry and its built-in `_UpdateSelectedRowHandler` survived inside
   the blob (the Display wrap depends on it).
4. **Level 3 — Hub/Display crossing.** Install the table into `HubDisplay` → push
   → assert an equal replica and that `bind_renderer_factory` rebound the real
   factory onto the table.
5. **Level 4 — the harness Scenarios.**
   - **Interactive** `table_row_select_progress`: a `table` beside a display-only
     `progress`. The injected interaction is a `row_selected` carrying the second
     row's `row_id`; the built-in state-sync flips the Hub `selected_row_id`, so
     the dispatch re-push carries the mutated `selected_row_id`
     (`PropAfterDispatch(field="selected_row_id", value="<row-2 id>")`). A wire
     `handlers` entry publishes `row_opened`; the agent reacts by advancing the
     progress. Proves the click crosses the faithful boundary, the Hub updates the
     authoritative selection once, and the re-push reflects it (Decision 1's
     publish path exercised).
   - **Reconcile-on-reorder** `table_reorder_keeps_selection`: select row with key
     `k`, re-push the rows in a different order (and with a row inserted), assert
     `selected_row_id` still equals `k` — the DES-045 payoff, the bug the legacy
     `row_index` had.
6. **Level 5 — introspection.** Query `inspect_scene`; assert the table's record
   reads `render_path == "abc"` and `resolved_props` reads back `columns`,
   `row_count`, and `selected_row_id`. After the interactive Scenario, assert the
   reported `selected_row_id` reflects the interaction (the Hub-authority payoff).
7. **Level 6 — live visual confirmation.** `make restart`; render the beads board
   through the real `lux:beads` skill / `show_table`; confirm by eye +
   `screenshot` that clicking a row highlights it and shows its detail, that
   filtering and scrolling do not disturb the selection, and that an agent-driven
   `selected_row_id` re-push moves the highlight with no user click; capture
   `inspect_scene` + `list_recent_events`; **operator confirms** before the kind
   is called done.

## 9. Report status

Design + verification plan only. No production code, tests, or introspection
implementation written. The five operator decisions are collected at the top in
liftable form; the settled DES-045 / DES-046 / DES-041 / DES-039 constraints are
treated as constraints, not reopened. Saved to
`docs/architecture/migration/table-design.md`.
