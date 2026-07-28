"""``TableChrome`` — the show_table composition's chrome builders.

The filter controls (a search ``input_text``, status ``combo``s), the grid/detail
region (a draggable split when there is detail), and the detail ``markdown``
itself, each wired to the shared ``FilteredTableModel``. ``TableComposition`` owns
the group assembly and delegates the chrome here. Open wire shapes (a filter's
``items``, a detail's ``fields``/``rows``/``body``) are validated fail-loud.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, final

from punt_lux.domain.interaction import ValueChanged
from punt_lux.domain.selection_interaction import RowSelectionChanged
from punt_lux.protocol.compositions.table_filter_handlers import (
    ComboFilterHandler,
    SearchFilterHandler,
)
from punt_lux.protocol.compositions.table_selection_handlers import (
    DetailBindingHandler,
)
from punt_lux.protocol.elements.combo import ComboElement
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.protocol.elements.markdown import MarkdownElement
from punt_lux.protocol.elements.value_change_handlers import ApplyPatchOnChange

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element
    from punt_lux.protocol.compositions.filtered_table_model import FilteredTableModel
    from punt_lux.protocol.compositions.table_composition import TableCompositionSpec
    from punt_lux.protocol.elements.table import TableElement

__all__ = ["TableChrome"]

# Initial grid (top) height fraction before any drag; a richer detail trims it.
_MAX_GRID_RATIO = 0.6
_MIN_GRID_RATIO = 0.5
_RATIO_PER_FIELD = 0.015


@final
class TableChrome:
    """Build the show_table composition's filter controls and detail region."""

    __slots__ = ()

    @staticmethod
    def default_grid_ratio(detail: dict[str, object] | None) -> float:
        """Return the split's initial grid height fraction, clamped to [0.5, 0.6].

        Proportioned to the detail's field count so a richer card opens a little
        taller; ``None`` has no split and the base fraction applies.
        """
        if detail is None:
            return _MAX_GRID_RATIO
        fields = detail.get("fields")
        count = len(cast("list[object]", fields)) if isinstance(fields, list) else 0
        trimmed = _MAX_GRID_RATIO - max(count - 4, 0) * _RATIO_PER_FIELD
        return min(max(trimmed, _MIN_GRID_RATIO), _MAX_GRID_RATIO)

    @classmethod
    def filter_controls(
        cls, spec: TableCompositionSpec, model: FilteredTableModel
    ) -> list[Element]:
        """Build the search input and combo controls, each wired to the model.

        An unrecognised filter ``type`` is rejected here fail-loud rather than
        silently dropped — a typo that produced no control is worse than an error.
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
            autofocus=True,  # the search is the composition's keyboard-focus target
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
        raw_items = TableChrome._require_list(
            filt.get("items", []), "combo filter 'items'"
        )
        items = [str(item) for item in raw_items]
        if not items:
            # An empty/omitted items list builds a choiceless control — fail loud.
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

    @classmethod
    def build_detail(
        cls,
        spec: TableCompositionSpec,
        table: TableElement,
        model: FilteredTableModel,
    ) -> MarkdownElement:
        """Build the detail region, binding it to the anchor and to filter changes.

        One binder drives on a selection gesture (``RowSelectionChanged``) and
        after a filter re-projection (``model.bind_detail``), so the panel tracks
        the anchor whether the user clicked or filtered.
        """
        placeholder = "Select a row to see its detail."
        region = MarkdownElement(id=f"{spec.table_id}-detail", content=placeholder)
        binder = DetailBindingHandler(
            region, content_by_id=cls._detail_content(spec), placeholder=placeholder
        )
        table.add_handler(RowSelectionChanged, binder)
        model.bind_detail(binder)
        return region

    @classmethod
    def _detail_content(cls, spec: TableCompositionSpec) -> dict[str, str]:
        """Return per-row-id markdown detail content from the parallel arrays."""
        detail = spec.detail or {}
        raw_fields = cls._require_list(detail.get("fields", []), "detail 'fields'")
        fields = [str(f) for f in raw_fields]
        detail_rows = cls._require_list(detail.get("rows", []), "detail 'rows'")
        bodies = cls._require_list(detail.get("body", []), "detail 'body'")
        content: dict[str, str] = {}
        for index, row in enumerate(spec.rows):
            if not 0 <= spec.key_column < len(row):
                continue
            raw_values: object = detail_rows[index] if index < len(detail_rows) else []
            values: list[object] = (
                cast("list[object]", raw_values) if isinstance(raw_values, list) else []
            )
            body = str(bodies[index]) if index < len(bodies) else ""
            content[str(row[spec.key_column])] = cls._detail_card(fields, values, body)
        return content

    @staticmethod
    def _detail_card(fields: list[str], values: list[object], body: str) -> str:
        """Return a markdown card: blank-line-separated field/value lines, then body."""
        lines = [
            f"**{field}:** {values[i] if i < len(values) else ''}"
            for i, field in enumerate(fields)
        ]
        return "\n\n".join([*lines, body]) if body else "\n\n".join(lines)

    @staticmethod
    def _require_list(value: object, name: str) -> list[object]:
        """Return ``value`` as a list, or raise a named ``ValueError``.

        The open wire shapes can arrive as ``None`` or a scalar; fail loud with the
        field name, not a bare ``TypeError`` deep in a comprehension.
        """
        if not isinstance(value, list):
            msg = f"table {name} must be a list, got {type(value).__name__}"
            raise ValueError(msg)
        return cast("list[object]", value)
