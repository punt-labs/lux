"""``TableComposition`` — build the show_table UI as element instances.

The one construction path for the ``show_table`` family: a basic grid alone
without chrome, or a ``group`` of a search input, status combos, and a
grid/detail split, with the Hub-side filter, selection-merge, and detail-binding
handlers wired over a shared ``FilteredTableModel``. ``ConvenienceOperations``
and ``apps.beads`` both call ``build``, so there is one composition, not two.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from punt_lux.protocol.compositions.filtered_table_model import FilteredTableModel
from punt_lux.protocol.compositions.table_chrome import TableChrome
from punt_lux.protocol.compositions.table_composition_spec import TableCompositionSpec
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.elements.split_pane import SplitPaneElement
from punt_lux.protocol.elements.table import TableElement
from punt_lux.protocol.elements.table_codec import install_selection_sync
from punt_lux.protocol.elements.table_flags import TableFlags

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element

__all__ = ["TableComposition", "TableCompositionSpec"]

_DEFAULT_FLAGS = ("borders", "row_bg")


@final
class TableComposition:
    """Build the scene roots for a show_table request as element instances."""

    __slots__ = ()

    @classmethod
    def build(cls, spec: TableCompositionSpec) -> list[Element]:
        """Return the scene roots: a basic grid, or a group with composed chrome.

        With a detail panel the grid and detail become the two panes of a
        ``SplitPaneElement`` whose divider the user drags; the initial proportion
        comes from the detail's field count. Without detail the grid stands alone.
        """
        if not spec.table_id.strip():
            # A blank table_id makes the table anonymous (the "" id sentinel) and
            # its synthesized control ids ambiguous; reject it here too so a direct
            # builder caller cannot construct an anonymous composition.
            msg = f"table_id must be a non-empty identifier, got {spec.table_id!r}"
            raise ValueError(msg)
        table = cls._grid(spec)
        install_selection_sync(table)
        if not spec.has_chrome:
            return [table]
        # The model observes the table, so every selection write (gesture or agent
        # patch) folds into its full selection — no separate merge handler needed.
        model = FilteredTableModel(
            all_rows=spec.rows,
            key_column=spec.key_column,
            search_columns=spec.search_columns(),
            table=table,
        )
        children = TableChrome.filter_controls(spec, model)
        children.append(cls._region(spec, table, model))
        return [
            GroupElement(id=f"{spec.table_id}-view", layout="rows", children=children)
        ]

    @staticmethod
    def _region(
        spec: TableCompositionSpec, table: TableElement, model: FilteredTableModel
    ) -> Element:
        """Return the grid, or a draggable grid/detail split when there is detail."""
        if spec.detail is None:
            return table
        detail = TableChrome.build_detail(spec, table, model)
        return SplitPaneElement(
            id=f"{spec.table_id}-split",
            top=table,
            bottom=detail,
            default_ratio=TableChrome.default_grid_ratio(spec.detail),
        )

    @staticmethod
    def _grid(spec: TableCompositionSpec) -> TableElement:
        """Build the basic grid; a table with chrome is selectable.

        The grid reserves no scroll lines: with detail it is the top pane of a
        split whose divider bounds it, so it takes its whole pane.
        """
        flags = spec.flags if spec.flags is not None else _DEFAULT_FLAGS
        return TableElement(
            id=spec.table_id,
            columns=spec.columns,
            rows=spec.rows,
            flags=TableFlags.from_wire(flags),
            key_column=spec.key_column,
            selection_mode=spec.selection_mode,
        )
