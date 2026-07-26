"""``FilteredTableModel`` — the Hub-side authority for a filtered table composition.

The element's ``selected_row_ids`` under a filter is only the *visible* projection
of the selection; on its own it would silently drop a selected-but-hidden row and
never restore it. This model owns the truth instead: the unfiltered ``all_rows``
and the **full** selection spanning hidden rows. A filter change re-projects the
element (``selected_row_ids`` becomes ``full`` intersect ``visible``) without
touching the full selection, so clearing the filter restores hidden selections —
the fix to the drop-on-filter blocker (table-design.md §6.1).

The model is held by the composition's filter and selection handlers as an
attribute and is serializable, so it travels inside the pickled scene blob and
lives on the authoritative Hub copy; it never runs on the Display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from punt_lux.protocol.compositions.table_selection_handlers import (
        DetailBindingHandler,
    )
    from punt_lux.protocol.elements.table import TableElement

__all__ = ["FilteredTableModel"]


class FilteredTableModel:
    """Owns the unfiltered rows and the full selection; projects onto the table."""

    _all_rows: tuple[tuple[object, ...], ...]
    _key_column: int
    _search_columns: tuple[int, ...]
    _table: TableElement
    _full_selection: set[str]
    _search: str
    _combo_picks: dict[int, str]
    # True only while the model is patching the table from its own re-projection,
    # so ``_on_table_change`` can tell its own filtered-subset ``rows`` write from
    # an external (agent) dataset write and not fold the subset in as the dataset.
    _reprojecting: bool
    # PY-TS-14 OK: genuinely optional — only a master/detail composition binds a
    # detail region; a plain filtered table has none.
    _detail: DetailBindingHandler | None

    def __new__(
        cls,
        *,
        all_rows: tuple[tuple[object, ...], ...],
        key_column: int,
        search_columns: tuple[int, ...],
        table: TableElement,
    ) -> Self:
        self = super().__new__(cls)
        self._all_rows = all_rows
        self._key_column = key_column
        self._search_columns = search_columns
        self._table = table
        # Seed from the table's initial selection, so a grid built with a seeded
        # selection (a rebuilt show_table) starts with a matching full selection.
        self._full_selection = set(table.selected_row_ids)
        self._search = ""
        self._combo_picks = {}
        self._reprojecting = False
        self._detail = None
        # Observe the table's writes so an agent apply_patch of selected_row_ids
        # OR rows folds into the model the same way a gesture/reproject does,
        # never shadowed on the next re-projection. Registered on __new__ only; a
        # pickled replica restores via object.__new__ and never mutates the Hub
        # copy, so it needs no observer of its own.
        table.add_observer(self._on_table_change)
        return self

    def bind_detail(self, detail: DetailBindingHandler) -> None:
        """Bind the detail region so a filter re-projection re-drives it too."""
        self._detail = detail

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport."""
        return (object.__new__, (type(self),), self.__dict__.copy())

    def __setstate__(self, state: dict[str, object]) -> None:
        """Restore instance state after native deserialization."""
        for key, value in state.items():
            object.__setattr__(self, key, value)

    @property
    def full_selection(self) -> frozenset[str]:
        """Return the authoritative full selection — what an agent reads (Decision 1).

        Spans rows currently hidden by the filter, never a filter-truncated view.
        """
        return frozenset(self._full_selection)

    def on_search(self, text: str) -> None:
        """Apply a new search term and re-project the visible rows + selection."""
        self._search = text
        self._reproject()

    def on_combo(self, column: int, chosen: str) -> None:
        """Apply a categorical filter on ``column`` (``"All"`` clears it)."""
        self._combo_picks[column] = chosen
        self._reproject()

    def on_selection_gesture(self, visible_selection: frozenset[str]) -> None:
        """Merge a user's visible pick into the full selection, keeping hidden rows.

        The new full selection is ``(full minus visible) union (visible_selection
        intersect visible)`` — the hidden part is preserved so a filter-clear
        restores it.
        """
        visible = self.visible_ids()
        self._full_selection = (self._full_selection - visible) | (
            visible_selection & visible
        )

    def _on_table_change(self, prop: str) -> None:
        """Fold a table write into the model (the observer callback).

        A ``selected_row_ids`` write — a gesture's built-in sync, an agent
        ``apply_patch``, or a filter re-projection's own patch — folds into the
        full selection and re-drives a bound detail through one shared path
        (visible-scoped and idempotent, so a re-projection's own write is a
        no-op). A ``rows`` write from *outside* the model (an agent refreshing the
        data) becomes the new dataset; the model's own re-projection writes the
        filtered subset, which the ``_reprojecting`` guard excludes so the subset
        is never folded in as the dataset. Other notifications (``removed``) are
        ignored.
        """
        if prop == "rows":
            if not self._reprojecting:
                self._absorb_dataset()
            return
        if prop != "selected_row_ids":
            return
        self.on_selection_gesture(self._table.selected_row_ids)
        if self._detail is not None:
            self._detail.render_anchor(self._table.anchor_row_id)

    def _absorb_dataset(self) -> None:
        """Adopt the table's rows as the new unfiltered dataset and re-project.

        The full selection reconciles against the new dataset — ids that vanished
        from the *data* leave it (a dataset change, unlike a filter, which keeps
        hidden ids for restore). The re-project then re-applies the active filter
        to the new rows.
        """
        self._all_rows = self._table.rows
        live = {self._row_id(row) for row in self._all_rows}
        self._full_selection &= live
        self._reproject()

    def visible_ids(self) -> frozenset[str]:
        """Return the ids of the rows the current filter leaves visible."""
        return frozenset(self._row_id(row) for row in self._visible_rows())

    def _reproject(self) -> None:
        """Patch the table with the visible rows + projected selection.

        The selection patch reseats the table's anchor onto a still-visible row
        (or clears it); the bound detail is re-driven from that anchor by the
        ``selected_row_ids`` observer (``_on_table_change``) — the one shared
        re-drive path — so the panel never keeps showing a row the filter hid.
        """
        visible = self._visible_rows()
        visible_ids = frozenset(self._row_id(row) for row in visible)
        self._reprojecting = True
        try:
            self._table.apply_patch(
                {
                    "rows": [list(row) for row in visible],
                    "selected_row_ids": sorted(self._full_selection & visible_ids),
                }
            )
        finally:
            self._reprojecting = False

    def _visible_rows(self) -> tuple[tuple[object, ...], ...]:
        """Return the unfiltered rows that pass the search and combo predicates."""
        needle = self._search.lower()
        return tuple(
            row
            for row in self._all_rows
            if self._matches_search(row, needle) and self._matches_combos(row)
        )

    def _matches_search(self, row: tuple[object, ...], needle: str) -> bool:
        """Return whether ``row`` contains ``needle`` in any searched column.

        A search declared with no resolvable columns (names, or a missing
        ``column``) searches *every* column rather than matching nothing, so a
        stray search config never silently empties the table.
        """
        if not needle:
            return True
        columns = self._search_columns or range(len(row))
        return any(
            needle in str(row[col]).lower() for col in columns if 0 <= col < len(row)
        )

    def _matches_combos(self, row: tuple[object, ...]) -> bool:
        """Return whether ``row`` satisfies every active categorical filter."""
        for column, chosen in self._combo_picks.items():
            if not chosen or chosen == "All":
                continue
            if not 0 <= column < len(row) or str(row[column]) != chosen:
                return False
        return True

    def _row_id(self, row: tuple[object, ...]) -> str:
        """Return ``row``'s stable id — its key-column cell as a string."""
        if 0 <= self._key_column < len(row):
            return str(row[self._key_column])
        return ""
