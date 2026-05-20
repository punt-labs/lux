"""Table elements — data tables with filters and detail panels."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import InitVar, dataclass, field
from typing import Any, Literal

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


def _table_detail_to_dict(d: TableDetail) -> dict[str, Any]:
    return {"fields": d.fields, "rows": d.rows, "body": d.body}


def _table_detail_from_dict(d: dict[str, Any]) -> TableDetail:
    return TableDetail(
        fields=d.get("fields", []),
        rows=d.get("rows", []),
        body=d.get("body", []),
    )


def _table_filter_to_dict(f: TableFilter) -> dict[str, Any]:
    d: dict[str, Any] = {"type": f.type, "column": f.column}
    if f.hint:
        d["hint"] = f.hint
    if f.items is not None:
        d["items"] = f.items
    if f.label:
        d["label"] = f.label
    return d


def _table_filter_from_dict(d: dict[str, Any]) -> TableFilter:
    ftype = d["type"]
    if ftype not in ("search", "combo"):
        msg = f"Unknown table filter type: {ftype!r}"
        raise ValueError(msg)
    return TableFilter(
        type=ftype,
        column_spec=d["column"],
        hint=d.get("hint", ""),
        items=d.get("items"),
        label=d.get("label", ""),
    )


def _table_to_dict(elem: TableElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "columns": elem.columns,
        "rows": elem.rows,
        "flags": elem.flags,
    }
    if elem.column_widths is not None:
        d["column_widths"] = elem.column_widths
    if elem.filters is not None:
        d["filters"] = [_table_filter_to_dict(f) for f in elem.filters]
    if elem.detail is not None:
        d["detail"] = _table_detail_to_dict(elem.detail)
    return d


def _table_from_dict(d: dict[str, Any]) -> TableElement:
    raw_filters = d.get("filters")
    raw_detail = d.get("detail")
    return TableElement(
        id=d["id"],
        columns=d.get("columns", []),
        rows=d.get("rows", []),
        flags=d.get("flags", ["borders", "row_bg"]),
        column_widths=d.get("column_widths"),
        filters=[_table_filter_from_dict(f) for f in raw_filters]
        if raw_filters is not None
        else None,
        detail=_table_detail_from_dict(raw_detail) if raw_detail is not None else None,
    )


_Register = Callable[
    [str, type, Callable[..., dict[str, Any]], Callable[[dict[str, Any]], Any]],
    None,
]


def register_codecs(register: _Register) -> None:
    """Register this module's element codecs into an ElementCodec."""
    register("table", TableElement, _table_to_dict, _table_from_dict)
