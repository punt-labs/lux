"""Wire-shape coercion for a table's ``rows``/``columns``.

Shared by ``JsonTableDecoder`` and the ``TableElement`` patch setters, so the two
paths agree on what a well-formed grid looks like on the wire. These check
*structure* only — that ``rows``/``columns`` are lists of the right shape — and
raise a typed ``ValueError`` at the decode boundary (PY-EH-1). Cell *content* (a
ragged row, a non-scalar cell) is left for ``validate`` to report (DES-039).
"""

from __future__ import annotations

from typing import cast, final

__all__ = ["TableWire"]


@final
class TableWire:
    """Stateless coercion of a table's wire ``rows``/``columns`` to typed tuples."""

    __slots__ = ()

    @staticmethod
    def rows_from_wire(value: object) -> tuple[tuple[object, ...], ...]:
        """Coerce a wire ``rows`` value to a tuple of row tuples.

        ``rows`` and each row must be a list, else ``ValueError``; cell content is
        a ``validate`` concern.
        """
        if not isinstance(value, list):
            msg = f"rows must be a list of rows, got {type(value).__name__}"
            raise ValueError(msg)
        rows: list[tuple[object, ...]] = []
        for index, row in enumerate(cast("list[object]", value)):
            if not isinstance(row, list):
                msg = f"row {index} must be a list of cells, got {type(row).__name__}"
                raise ValueError(msg)
            rows.append(tuple(cast("list[object]", row)))
        return tuple(rows)

    @classmethod
    def columns_from_wire(cls, value: object) -> tuple[str, ...]:
        """Coerce a wire ``columns`` value to a tuple of header strings."""
        return tuple(cls.str_list(value, "columns"))

    @staticmethod
    def str_list(value: object, field: str) -> list[str]:
        """Return ``value`` as a list of strings or raise a named ``ValueError``."""
        got = type(value).__name__
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in cast("list[object]", value)
        ):
            msg = f"{field} must be a list of strings, got {got}"
            raise ValueError(msg)
        return list(cast("list[str]", value))
