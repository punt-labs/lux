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
        self._full_selection = set()
        self._search = ""
        self._combo_picks = {}
        return self

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

    def visible_ids(self) -> frozenset[str]:
        """Return the ids of the rows the current filter leaves visible."""
        return frozenset(self._row_id(row) for row in self._visible_rows())

    def _reproject(self) -> None:
        """Patch the table with the visible rows and the projected selection."""
        visible = self._visible_rows()
        visible_ids = frozenset(self._row_id(row) for row in visible)
        self._table.apply_patch(
            {
                "rows": [list(row) for row in visible],
                "selected_row_ids": sorted(self._full_selection & visible_ids),
            }
        )

    def _visible_rows(self) -> tuple[tuple[object, ...], ...]:
        """Return the unfiltered rows that pass the search and combo predicates."""
        needle = self._search.lower()
        return tuple(
            row
            for row in self._all_rows
            if self._matches_search(row, needle) and self._matches_combos(row)
        )

    def _matches_search(self, row: tuple[object, ...], needle: str) -> bool:
        """Return whether ``row`` contains ``needle`` in any searched column."""
        if not needle:
            return True
        return any(
            needle in str(row[col]).lower()
            for col in self._search_columns
            if 0 <= col < len(row)
        )

    def _matches_combos(self, row: tuple[object, ...]) -> bool:
        """Return whether ``row`` satisfies every active categorical filter."""
        for column, chosen in self._combo_picks.items():
            if not chosen or chosen == "All":
                continue
            if column >= len(row) or str(row[column]) != chosen:
                return False
        return True

    def _row_id(self, row: tuple[object, ...]) -> str:
        """Return ``row``'s stable id — its key-column cell as a string."""
        if 0 <= self._key_column < len(row):
            return str(row[self._key_column])
        return ""
