"""Display-local table sort — the real reorder the legacy ``sortable`` flag lacked.

Pure, testable reordering of the *displayed* rows by ImGui's sort specs; the
authoritative row order is untouched, and the selection survives because it is
keyed by ``row_id``, not position. Cells are mixed scalars, so the sort key
groups them (null < number < string) to order deterministically without raising
on a heterogeneous column.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["TableSort"]


@final
class TableSort:
    """Reorder ``(row_id, row)`` pairs by a stack of column sort specs."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def order(
        self,
        pairs: list[tuple[str, tuple[object, ...]]],
        specs: tuple[tuple[int, bool], ...],
    ) -> list[tuple[str, tuple[object, ...]]]:
        """Return ``pairs`` reordered by ``specs`` (``(column_index, ascending)``).

        Specs are applied least-significant first over Python's stable sort, so a
        multi-column sort matches ImGui's spec order. An out-of-range column is
        skipped.
        """
        ordered = list(pairs)
        for column, ascending in reversed(specs):
            ordered.sort(key=self._key_for(column), reverse=not ascending)
        return ordered

    def _key_for(
        self, column: int
    ) -> Callable[[tuple[str, tuple[object, ...]]], tuple[int, float, str]]:
        """Return a sort-key function bound to ``column`` (closes it correctly)."""

        def key(pair: tuple[str, tuple[object, ...]]) -> tuple[int, float, str]:
            return self._cell_key(pair[1], column)

        return key

    @staticmethod
    def _cell_key(row: tuple[object, ...], column: int) -> tuple[int, float, str]:
        """Return a total-order key for ``row``'s cell in ``column``."""
        cell = row[column] if 0 <= column < len(row) else None
        if cell is None:
            return (0, 0.0, "")
        if isinstance(cell, bool):
            return (1, float(cell), "")
        if isinstance(cell, int | float):
            return (1, float(cell), "")
        return (2, 0.0, str(cell))
