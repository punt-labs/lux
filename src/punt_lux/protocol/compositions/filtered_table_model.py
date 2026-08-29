"""``FilteredTableModel`` — the Hub-side authority for a filtered table composition.

The element's ``selected_row_ids`` under a filter is only the *visible* projection
of the selection; on its own it would silently drop a selected-but-hidden row and
never restore it. This model owns the truth instead: the unfiltered ``all_rows``
and the **full** selection spanning hidden rows. A filter change re-projects the
element without touching the full selection, so clearing the filter restores it.

Held by the composition's filter/selection handlers, serializable so it travels
inside the pickled scene blob to the authoritative Hub copy; never runs on the
Display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

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
    # True only during the model's own patch, so ``_on_table_change`` can tell its
    # filtered-subset write from an external (agent) dataset write.
    _reprojecting: bool
    # PY-TS-14 OK: optional — only a master/detail composition binds one.
    _detail: DetailBindingHandler | None
    # Memoizes the visible-row scan by (rows identity, filter state); ``None`` is
    # "nothing cached yet" (PY-TS-14).
    _visible_cache_key: tuple[int, str, frozenset[tuple[int, str]]] | None
    _visible_cache_rows: tuple[tuple[object, ...], ...] | None
    _visible_cache_ids: frozenset[str] | None

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
        # Seed from the table's initial selection (a rebuilt show_table's seed).
        self._full_selection = set(table.selected_row_ids)
        self._search = ""
        self._combo_picks = {}
        self._reprojecting = False
        self._detail = None
        self._visible_cache_key = None
        self._visible_cache_rows = None
        self._visible_cache_ids = None
        # __new__-only: an apply_patch folds in like a gesture; a pickled replica
        # restores via object.__new__ and never mutates the Hub copy.
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
        """Return the authoritative full selection an agent reads (Decision 1).

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

        New full = (full minus visible) union (visible_selection intersect
        visible) — hidden ids survive so a filter-clear restores them.
        """
        visible = self.visible_ids()
        self._full_selection = (self._full_selection - visible) | (
            visible_selection & visible
        )

    def _on_table_change(self, prop: str) -> None:
        """Fold a table write into the model (the observer callback).

        ``selected_row_ids`` folds into the full selection and re-drives a
        detail (idempotent, so the model's own write is a no-op). ``rows`` from
        *outside* the model becomes the new dataset; ``_reprojecting`` excludes
        the model's own filtered-subset write.
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
        """Adopt the table's rows as the new dataset, reconcile, and re-project.

        Ids missing from the new data leave the full selection (unlike a
        filter, which keeps hidden ids); the element's committed selection then
        folds in, atomic regardless of commit-flush order.
        """
        self._all_rows = self._table.rows
        live = {self._row_id(row) for row in self._all_rows}
        self._full_selection &= live
        self.on_selection_gesture(self._table.selected_row_ids)
        self._reproject()

    def visible_ids(self) -> frozenset[str]:
        """Return the ids of the rows the filter leaves visible (shares the cache
        ``_visible_rows`` fills, so an ids-only caller never re-derives them)."""
        self._visible_rows()
        return cast("frozenset[str]", self._visible_cache_ids)

    def _reproject(self) -> None:
        """Patch the table with the visible rows + projected selection.

        The selection patch reseats the anchor onto a still-visible row (or
        clears it); ``_on_table_change`` re-drives a bound detail from that
        anchor, so the panel never keeps showing a row the filter hid.
        """
        visible = self._visible_rows()
        visible_ids = self.visible_ids()
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
        """Return the unfiltered rows passing the search/combo predicates, memoized
        by ``(rows identity, filter state)`` so an unchanged call (e.g. every
        render frame) skips the rescan."""
        key = (id(self._all_rows), self._search, frozenset(self._combo_picks.items()))
        if self._visible_cache_rows is not None and key == self._visible_cache_key:
            return self._visible_cache_rows
        visible = self._scan_visible_rows()
        self._visible_cache_key = key
        self._visible_cache_rows = visible
        self._visible_cache_ids = frozenset(self._row_id(row) for row in visible)
        return visible

    def _scan_visible_rows(self) -> tuple[tuple[object, ...], ...]:
        """Scan ``_all_rows`` and return those passing the search/combo predicates."""
        needle = self._search.lower()
        return tuple(
            row
            for row in self._all_rows
            if self._matches_search(row, needle) and self._matches_combos(row)
        )

    def _matches_search(self, row: tuple[object, ...], needle: str) -> bool:
        """Return whether ``row`` contains ``needle`` in any searched column.

        No resolvable columns searches *every* column, so a stray search config
        never silently empties the table.
        """
        if not needle:
            return True
        columns = self._search_columns or range(len(row))
        return any(
            needle in str(row[col]).lower() for col in columns if 0 <= col < len(row)
        )

    def _matches_combos(self, row: tuple[object, ...]) -> bool:
        """Return whether ``row`` satisfies every active categorical filter."""
        return all(
            0 <= column < len(row) and str(row[column]) == chosen
            for column, chosen in self._combo_picks.items()
            if chosen and chosen != "All"
        )

    def _row_id(self, row: tuple[object, ...]) -> str:
        """Return ``row``'s stable id — its key-column cell as a string."""
        if 0 <= self._key_column < len(row):
            return str(row[self._key_column])
        return ""
