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

from punt_lux.protocol.compositions.filtered_table_model import FilteredTableModel
from punt_lux.protocol.compositions.table_chrome import TableChrome
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.elements.table import TableElement
from punt_lux.protocol.elements.table_codec import install_selection_sync
from punt_lux.protocol.elements.table_flags import TableFlags
from punt_lux.protocol.elements.table_selection_model import SelectionMode

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element

__all__ = ["TableComposition", "TableCompositionSpec"]

_DEFAULT_FLAGS = ("borders", "row_bg")


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
        children = TableChrome.filter_controls(spec, model)
        children.append(table)
        TableChrome.append_detail(spec, table, model, children)
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
            scroll_reserve_lines=TableChrome.detail_reserve_lines(spec.detail),
        )
