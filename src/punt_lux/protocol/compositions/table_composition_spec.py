"""``TableCompositionSpec`` — the validated inputs a show_table build reads.

The frozen value object ``TableComposition.build`` consumes: the columns and
rows, the open wire shapes for filters and detail, and the derivations the
builder asks of them (chrome presence, selection mode, in-range search columns).
Kept in its own module so the composition builder stays one class per file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from punt_lux.protocol.elements.table_selection_model import SelectionMode

__all__ = ["TableCompositionSpec"]


@dataclass(frozen=True, slots=True)
class TableCompositionSpec:
    """The inputs a show_table composition is built from.

    ``filters`` and ``detail`` are open wire shapes (PY-TS-14 wire boundary): the
    tool passes them as dicts and the composition reads the keys it recognises.
    """

    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    filters: tuple[dict[str, object], ...] = ()
    detail: dict[str, object] | None = None
    flags: tuple[str, ...] | None = None
    key_column: int = 0
    table_id: str = "table"

    @property
    def has_chrome(self) -> bool:
        """Return whether the composition needs a filter bar or a detail panel."""
        return bool(self.filters) or self.detail is not None

    @property
    def selection_mode(self) -> SelectionMode:
        """Return the grid's selection mode implied by its chrome."""
        if self.detail is not None:
            return "single"  # detail binds to a single anchor row
        return "multi" if self.filters else "none"

    def search_columns(self) -> tuple[int, ...]:
        """Return the in-range int columns the search filter matches, ``()`` if none.

        Out-of-range indices are dropped at build time, so an all-out-of-range
        config yields ``()`` and the model's search falls open to every column.
        """
        num_columns = len(self.columns)
        for spec in self.filters:
            if spec.get("type") == "search":
                column = spec.get("column", [])
                cols: list[object] = (
                    cast("list[object]", column)
                    if isinstance(column, list)
                    else [column]
                )
                return tuple(
                    c
                    for c in cols
                    if isinstance(c, int)
                    and not isinstance(c, bool)
                    and 0 <= c < num_columns
                )
        return ()
