"""Table elements — data tables with filters and detail panels."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from typing import Any, Literal, Self, cast

from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements.codec import Register

__all__ = [
    "TableDetail",
    "TableElement",
    "TableFilter",
    "register_codecs",
]


@dataclass(frozen=True, slots=True)
class TableFilter:
    """A built-in filter control rendered above a table.

    - ``search``: case-insensitive substring match on specified column(s).
    - ``combo``: exact match dropdown; first item is treated as "All" (no filter).
    """

    type: Literal["search", "combo"]
    column_spec: InitVar[int | list[int]]
    hint: str = ""  # placeholder text (search only)
    items: list[str] | None = None  # dropdown items (combo only)
    label: str = ""  # optional label for the control
    _column: list[int] = field(init=False)

    def __post_init__(self, column_spec: int | list[int]) -> None:
        col = [column_spec] if isinstance(column_spec, int) else list(column_spec)
        if not col:
            msg = "TableFilter requires non-empty 'column'"
            raise ValueError(msg)
        if self.type == "combo" and not self.items:
            msg = "TableFilter type='combo' requires non-empty 'items'"
            raise ValueError(msg)
        object.__setattr__(self, "_column", col)

    @property
    def column(self) -> list[int]:
        """Column index(es) this filter operates on (read-only)."""
        return list(self._column)

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-compatible wire representation."""
        d: dict[str, Any] = {"type": self.type, "column": self.column}
        if self.hint:
            d["hint"] = self.hint
        if self.items is not None:
            d["items"] = self.items
        if self.label:
            d["label"] = self.label
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Construct a TableFilter from a JSON-decoded mapping."""
        ftype = d["type"]
        if ftype not in ("search", "combo"):
            msg = f"Unknown table filter type: {ftype!r}"
            raise ValueError(msg)
        return cls(
            type=ftype,
            column_spec=d["column"],
            hint=d.get("hint", ""),
            items=d.get("items"),
            label=d.get("label", ""),
        )


@dataclass(frozen=True, slots=True)
class TableDetail:
    """Detail data for a built-in list/detail view.

    Each array is parallel to the parent ``TableElement.rows``:
    ``rows[i]`` provides the detail metadata and ``body[i]`` provides
    the long-form text for the *i*-th list row.

    ``fields`` names the metadata columns.  The display renders them
    as a 2-column grid (Field | Value | Field | Value).
    """

    fields: list[str]
    rows: list[list[Any]]
    body: list[str]

    def __post_init__(self) -> None:
        if len(self.rows) != len(self.body):
            msg = (
                "TableDetail rows/body length mismatch: "
                f"{len(self.rows)} vs {len(self.body)}"
            )
            raise ValueError(msg)

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-compatible wire representation."""
        return {"fields": self.fields, "rows": self.rows, "body": self.body}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Construct a TableDetail from a JSON-decoded mapping."""
        return cls(
            fields=d.get("fields", []),
            rows=d.get("rows", []),
            body=d.get("body", []),
        )


@dataclass(frozen=True, slots=True)
class TableElement:
    """A data table with columns and rows."""

    id: str
    kind: Literal["table"] = "table"
    columns: list[str] = field(default_factory=lambda: list[str]())
    rows: list[list[Any]] = field(default_factory=lambda: list[list[Any]]())
    flags: list[str] = field(default_factory=lambda: ["borders", "row_bg"])
    column_widths: list[float] | None = None
    filters: list[TableFilter] | None = None
    detail: TableDetail | None = None
    tooltip: str | None = None

    def __post_init__(self) -> None:
        cw = self.column_widths
        if cw is not None and len(cw) != len(self.columns):
            msg = (
                f"column_widths length ({len(cw)}) "
                f"must match columns ({len(self.columns)})"
            )
            raise ValueError(msg)
        d = self.detail
        if d is not None and len(d.rows) != len(self.rows):
            msg = (
                f"detail.rows length ({len(d.rows)}) must match rows ({len(self.rows)})"
            )
            raise ValueError(msg)

    def validate(self) -> tuple[ValidationError, ...]:
        """Return errors where the agent's data does not fit the table widget.

        Component-appropriate checks — what "valid" means for a *table*:

        - ``columns`` and ``rows`` are each a list (a present-but-``null``
          field decodes to ``None`` and must be reported, not crash the walk);
        - every row is itself a list of cells;
        - every row has exactly one cell per declared column;
        - every cell is a scalar the widget can render as text
          (``str``, ``int``, ``float``, ``bool``, or ``None``). A list or
          dict in a cell is a data-shape mistake the agent should fix
          rather than a value the table can paint.
        """
        return self._data_errors(self.columns, self.rows)

    def _data_errors(
        self,
        columns: object,
        rows: object,
    ) -> tuple[ValidationError, ...]:
        """Return errors for the ``columns``/``rows`` pair.

        Takes ``object`` parameters because the wire boundary can hand us a
        present ``null`` for either field (``dict.get`` returns the value,
        not the default), so the declared list types do not hold at decode
        time. The function boundary re-widens to ``object`` for the runtime
        list check, mirroring ``TreeElement._node_errors``.
        """
        if not isinstance(columns, list):
            return (self._error("columns must be a list of column names"),)
        if not isinstance(rows, list):
            return (self._error("rows must be a list of rows"),)
        column_count = len(cast("list[object]", columns))
        errors: list[ValidationError] = []
        for row_index, row in enumerate(cast("list[object]", rows)):
            if not isinstance(row, list):
                errors.append(self._error(f"row {row_index} is not a list of cells"))
                continue
            cells = cast("list[object]", row)
            if len(cells) != column_count:
                errors.append(
                    self._error(
                        f"row {row_index} has {len(cells)} cell(s) but the "
                        f"table declares {column_count} column(s)",
                    ),
                )
            errors.extend(self._cell_errors(row_index, cells))
        return tuple(errors)

    def _error(self, message: str) -> ValidationError:
        """Build a table ValidationError carrying this table's identity."""
        return ValidationError(
            element_id=self.id,
            element_kind=self.kind,
            message=message,
        )

    def _cell_errors(
        self,
        row_index: int,
        row: list[object],
    ) -> tuple[ValidationError, ...]:
        """Return one error per cell in ``row`` that the widget can't render."""
        errors: list[ValidationError] = []
        for col_index, cell in enumerate(row):
            if not isinstance(cell, str | int | float | type(None)):
                errors.append(
                    ValidationError(
                        element_id=self.id,
                        element_kind=self.kind,
                        message=(
                            f"row {row_index} column {col_index} holds a "
                            f"{type(cell).__name__}; table cells must be a "
                            "string, number, boolean, or null"
                        ),
                    ),
                )
        return tuple(errors)

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-compatible wire representation."""
        d: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "columns": self.columns,
            "rows": self.rows,
            "flags": self.flags,
        }
        if self.column_widths is not None:
            d["column_widths"] = self.column_widths
        if self.filters is not None:
            d["filters"] = [f.to_dict() for f in self.filters]
        if self.detail is not None:
            d["detail"] = self.detail.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Construct a TableElement from a JSON-decoded mapping."""
        raw_filters = d.get("filters")
        raw_detail = d.get("detail")
        return cls(
            id=d["id"],
            columns=d.get("columns", []),
            rows=d.get("rows", []),
            flags=d.get("flags", ["borders", "row_bg"]),
            column_widths=d.get("column_widths"),
            filters=[TableFilter.from_dict(f) for f in raw_filters]
            if raw_filters is not None
            else None,
            detail=TableDetail.from_dict(raw_detail)
            if raw_detail is not None
            else None,
        )


def register_codecs(register: Register) -> None:
    """Register this module's element codecs into an ElementCodec."""
    register("table", TableElement, TableElement.to_dict, TableElement.from_dict)
