"""``TableComposition`` — build the show_table UI as element instances.

The one construction path for the ``show_table`` family: a basic grid alone when
there is no chrome, or a ``group`` stacking a search ``input_text``, status
``combo``s, the basic ``table``, and a ``markdown`` detail region when there is —
with the Hub-side filter, selection-merge, and detail-binding handlers wired over
a shared ``FilteredTableModel``. ``build`` returns the scene roots;
``ConvenienceOperations`` and ``apps.beads`` both call it, so there is one
composition, not two.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, final

from punt_lux.domain.interaction import ValueChanged
from punt_lux.domain.selection_interaction import RowSelectionChanged
from punt_lux.protocol.compositions.filtered_table_model import FilteredTableModel
from punt_lux.protocol.compositions.table_filter_handlers import (
    ComboFilterHandler,
    SearchFilterHandler,
)
from punt_lux.protocol.compositions.table_selection_handlers import (
    DetailBindingHandler,
)
from punt_lux.protocol.elements.combo import ComboElement
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.protocol.elements.markdown import MarkdownElement
from punt_lux.protocol.elements.table import TableElement
from punt_lux.protocol.elements.table_codec import install_selection_sync
from punt_lux.protocol.elements.table_flags import TableFlags
from punt_lux.protocol.elements.table_selection_model import SelectionMode
from punt_lux.protocol.elements.value_change_handlers import ApplyPatchOnChange

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element

__all__ = ["TableComposition", "TableCompositionSpec"]

_DEFAULT_FLAGS = ("borders", "row_bg")


_MIN_DETAIL_RESERVE = 6  # a detail always gets at least this many lines
_MAX_DETAIL_RESERVE = 16  # cap so a big detail never starves the grid


def _detail_reserve_lines(detail: dict[str, object] | None) -> int:
    """Return the text lines the grid reserves below itself for ``detail``.

    Proportioned to the detail's field count (its cards are field lines plus a
    short body), clamped to ``[6, 16]`` so the panel is always visible without
    swallowing the grid. ``None`` (no detail) reserves nothing.
    """
    if detail is None:
        return 0
    fields = detail.get("fields")
    field_count = len(cast("list[object]", fields)) if isinstance(fields, list) else 0
    return min(max(field_count + 4, _MIN_DETAIL_RESERVE), _MAX_DETAIL_RESERVE)


def _require_list(value: object, name: str) -> list[object]:
    """Return ``value`` as a list, or raise a named ``ValueError``.

    The open wire shapes (a filter's ``items``, a detail's ``fields``/``rows``/
    ``body``) can arrive as ``None`` or a scalar; fail loud with the field name,
    the composition's own principle, rather than raise a bare ``TypeError`` deep
    in a comprehension.
    """
    if not isinstance(value, list):
        msg = f"table {name} must be a list, got {type(value).__name__}"
        raise ValueError(msg)
    return cast("list[object]", value)


@dataclass(frozen=True, slots=True)
class TableCompositionSpec:
    """The inputs a show_table composition is built from.

    ``filters`` and ``detail`` are open wire shapes (PY-TS-14 wire boundary): the
    tool surface passes them through as dicts and the composition reads the keys
    it recognises (``type``/``column``/``items`` for a filter; ``fields``/``rows``
    /``body`` for detail).
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
        """Return the *in-range* int columns the search filter matches, ``()`` if none.

        Out-of-range indices are dropped here at build time (the same discipline
        as the combo range check), so an all-out-of-range config yields ``()`` and
        the model's search falls open to every column rather than matching nothing.
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


@final
class TableComposition:
    """Build the scene roots for a show_table request as element instances."""

    __slots__ = ()

    @classmethod
    def build(cls, spec: TableCompositionSpec) -> list[Element]:
        """Return the scene roots: a basic grid, or a group with composed chrome."""
        if not spec.table_id.strip():
            # An empty/whitespace table_id would make the table anonymous (the ""
            # element-id sentinel) and its synthesized control ids ambiguous. The
            # invariant lives here too, so a direct builder caller cannot construct
            # an anonymous composition.
            msg = f"table_id must be a non-empty identifier, got {spec.table_id!r}"
            raise ValueError(msg)
        table = cls._grid(spec)
        install_selection_sync(table)
        if not spec.has_chrome:
            return [table]
        # The model registers itself as an observer of the table, so every
        # selection write (gesture sync or agent apply_patch) folds into its full
        # selection — no separate merge handler on RowSelectionChanged is needed.
        model = FilteredTableModel(
            all_rows=spec.rows,
            key_column=spec.key_column,
            search_columns=spec.search_columns(),
            table=table,
        )
        children = cls._filter_controls(spec, model)
        children.append(table)
        cls._append_detail(spec, table, model, children)
        return [
            GroupElement(id=f"{spec.table_id}-view", layout="rows", children=children)
        ]

    @staticmethod
    def _grid(spec: TableCompositionSpec) -> TableElement:
        """Build the basic grid; a table with chrome is selectable.

        When a detail panel follows the grid, the grid reserves space below its
        scroll region (``scroll_reserve_lines``) so the detail stays visible
        instead of being pushed off the bottom of the frame.
        """
        flags = spec.flags if spec.flags is not None else _DEFAULT_FLAGS
        return TableElement(
            id=spec.table_id,
            columns=spec.columns,
            rows=spec.rows,
            flags=TableFlags.from_wire(flags),
            key_column=spec.key_column,
            selection_mode=spec.selection_mode,
            scroll_reserve_lines=_detail_reserve_lines(spec.detail),
        )

    # -- filter controls ---------------------------------------------------

    @classmethod
    def _filter_controls(
        cls, spec: TableCompositionSpec, model: FilteredTableModel
    ) -> list[Element]:
        """Build the search input and combo controls, each wired to the model.

        An unrecognised filter ``type`` is rejected here (fail-loud, like
        ``TableFlags.from_wire``) rather than silently dropped — a typo that
        produced no control with no feedback is worse than an error.
        """
        controls: list[Element] = []
        num_columns = len(spec.columns)
        for index, filt in enumerate(spec.filters):
            kind = filt.get("type")
            if kind == "search":
                controls.append(cls._search_input(spec.table_id, filt, model))
            elif kind == "combo":
                controls.append(
                    cls._combo(spec.table_id, index, filt, model, num_columns)
                )
            else:
                msg = f"unknown table filter type {kind!r} (want 'search' or 'combo')"
                raise ValueError(msg)
        return controls

    @staticmethod
    def _search_input(
        table_id: str, filt: dict[str, object], model: FilteredTableModel
    ) -> InputTextElement:
        """Build a search input mirroring its value and driving the filter."""
        search = InputTextElement(
            id=f"{table_id}-search",
            label=str(filt.get("label", "Search")),
            hint=str(filt.get("hint", "")),
        )
        search.add_handler(ValueChanged, ApplyPatchOnChange(search, field="value"))
        search.add_handler(ValueChanged, SearchFilterHandler(model))
        return search

    @staticmethod
    def _combo(
        table_id: str,
        index: int,
        filt: dict[str, object],
        model: FilteredTableModel,
        num_columns: int,
    ) -> ComboElement:
        """Build a categorical combo mirroring its value and driving the filter."""
        raw_items = _require_list(filt.get("items", []), "combo filter 'items'")
        items = [str(item) for item in raw_items]
        if not items:
            # An empty/omitted items list builds a choiceless control — fail loud,
            # matching the legacy TableFilter contract and the other build guards.
            msg = f"combo filter {index} 'items' must be a non-empty list"
            raise ValueError(msg)
        raw_column = filt.get("column", 0)
        if isinstance(raw_column, bool) or not isinstance(raw_column, int):
            got = type(raw_column).__name__
            msg = f"combo filter 'column' must be an int index, got {got}"
            raise ValueError(msg)
        if not 0 <= raw_column < num_columns:
            msg = (
                f"combo filter 'column' {raw_column} is out of range for "
                f"{num_columns} columns"
            )
            raise ValueError(msg)
        column = raw_column
        combo = ComboElement(
            id=f"{table_id}-filter-{index}",
            label=str(filt.get("label", "")),
            items=items,
        )
        combo.add_handler(ValueChanged, ApplyPatchOnChange(combo, field="selected"))
        combo.add_handler(
            ValueChanged,
            ComboFilterHandler(model, column=column, items=tuple(items)),
        )
        return combo

    # -- detail region -----------------------------------------------------

    @classmethod
    def _append_detail(
        cls,
        spec: TableCompositionSpec,
        table: TableElement,
        model: FilteredTableModel,
        children: list[Element],
    ) -> None:
        """Append a detail region, binding it to the anchor and to filter changes.

        The same binder drives on a selection gesture (a ``RowSelectionChanged``
        handler) and after a filter re-projection (``model.bind_detail``), so the
        panel tracks the anchor whether the user clicked or filtered.
        """
        if spec.detail is None:
            return
        placeholder = "Select a row to see its detail."
        region = MarkdownElement(id=f"{spec.table_id}-detail", content=placeholder)
        binder = DetailBindingHandler(
            region, content_by_id=cls._detail_content(spec), placeholder=placeholder
        )
        table.add_handler(RowSelectionChanged, binder)
        model.bind_detail(binder)
        children.append(region)

    @staticmethod
    def _detail_content(spec: TableCompositionSpec) -> dict[str, str]:
        """Return per-row-id markdown detail content from the parallel arrays."""
        detail = spec.detail or {}
        raw_fields = _require_list(detail.get("fields", []), "detail 'fields'")
        fields = [str(f) for f in raw_fields]
        detail_rows = _require_list(detail.get("rows", []), "detail 'rows'")
        bodies = _require_list(detail.get("body", []), "detail 'body'")
        content: dict[str, str] = {}
        for index, row in enumerate(spec.rows):
            if not 0 <= spec.key_column < len(row):
                continue
            raw_values: object = detail_rows[index] if index < len(detail_rows) else []
            values: list[object] = (
                cast("list[object]", raw_values) if isinstance(raw_values, list) else []
            )
            body = str(bodies[index]) if index < len(bodies) else ""
            content[str(row[spec.key_column])] = TableComposition._detail_card(
                fields, values, body
            )
        return content

    @staticmethod
    def _detail_card(fields: list[str], values: list[object], body: str) -> str:
        """Return a markdown detail card: bold field/value lines then the body."""
        lines = [
            f"**{field}:** {values[i] if i < len(values) else ''}"
            for i, field in enumerate(fields)
        ]
        return "\n\n".join(["\n".join(lines), body]) if body else "\n".join(lines)
