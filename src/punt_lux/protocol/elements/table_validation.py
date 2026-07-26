"""``TableValidator`` — the basic grid's self-validation (DES-039).

Split from ``TableElement`` so the element stays focused on its data, wire, and
interaction surface and the validation rules live in one focused place. It reads
the element through its public accessors and reports what does not fit the grid:
always the rows-vs-columns shape and renderable cells, and — only when the grid
is selectable — the key column, the key values, and the selection set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.validation import ValidationError

if TYPE_CHECKING:
    from punt_lux.protocol.elements.table import TableElement

__all__ = ["TableValidator"]

_SCALAR = (str, int, float, type(None))


@final
class TableValidator:
    """Collect a ``TableElement``'s self-validation errors."""

    _elem: TableElement
    __slots__ = ("_elem",)

    def __new__(cls, elem: TableElement) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        return self

    def errors(self) -> tuple[ValidationError, ...]:
        """Return every error: the always-on grid checks plus the selection checks.

        A display-only (``none``) grid has no key-column constraint — a repeated
        key column is fine; only a selectable grid checks the key and selection.
        """
        errors = list(self._grid_errors())
        if self._elem.selection_mode != "none":
            errors.extend(self._selection_errors())
        return tuple(errors)

    def _grid_errors(self) -> tuple[ValidationError, ...]:
        """Return the always-on errors: ragged rows and non-scalar cells."""
        width = len(self._elem.columns)
        errors: list[ValidationError] = []
        for row_index, row in enumerate(self._elem.rows):
            if len(row) != width:
                errors.append(
                    self._error(
                        f"row {row_index} has {len(row)} cell(s) but the table "
                        f"declares {width} column(s)"
                    )
                )
            errors.extend(self._cell_errors(row_index, row))
        return tuple(errors)

    def _cell_errors(
        self, row_index: int, row: tuple[object, ...]
    ) -> tuple[ValidationError, ...]:
        """Return one error per non-scalar cell in ``row``."""
        errors: list[ValidationError] = []
        for col_index, cell in enumerate(row):
            if not isinstance(cell, _SCALAR):
                errors.append(
                    self._error(
                        f"row {row_index} column {col_index} holds a "
                        f"{type(cell).__name__}; table cells must be a string, "
                        "number, boolean, or null"
                    )
                )
        return tuple(errors)

    def _selection_errors(self) -> tuple[ValidationError, ...]:
        """Return the selectable-only errors: key column and selection set."""
        elem = self._elem
        if not 0 <= elem.key_column < len(elem.columns):
            return (self._error(f"key_column {elem.key_column} names no column"),)
        selected = elem.selected_row_ids
        live = frozenset(elem.row_id(row) for row in elem.rows)
        errors = list(self._key_value_errors())
        errors.extend(
            self._error(f"selected id {row_id!r} names no row")
            for row_id in sorted(selected - live)
        )
        if elem.selection_mode == "single" and len(selected) > 1:
            errors.append(self._error("single-select holds more than one row"))
        anchor = elem.anchor_row_id
        if anchor and anchor not in selected:
            errors.append(self._error(f"anchor {anchor!r} is not a selected row"))
        return tuple(errors)

    def _key_value_errors(self) -> tuple[ValidationError, ...]:
        """Return errors for empty or duplicate key-column values."""
        elem = self._elem
        errors: list[ValidationError] = []
        seen: set[str] = set()
        for row_index, row in enumerate(elem.rows):
            if len(row) <= elem.key_column:
                continue  # raggedness already reported by the grid checks
            key = elem.row_id(row)
            if not key:
                errors.append(self._error(f"row {row_index} has an empty key value"))
            elif key in seen:
                errors.append(self._error(f"duplicate key value {key!r}"))
            seen.add(key)
        return tuple(errors)

    def _error(self, message: str) -> ValidationError:
        """Build a table ValidationError carrying the element's identity."""
        return ValidationError(
            element_id=self._elem.id, element_kind=self._elem.kind, message=message
        )
