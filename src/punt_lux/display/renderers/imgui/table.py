# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""ImGuiTableRenderer — the ImGui adapter for the ABC basic grid.

A ``LeafRenderer``: it paints one widget (the grid) and has no child elements, so
``LeafRenderer`` records its geometry and runs the shared tooltip pass around the
paint. The grid renders in a native ImGui scroll region (no pager); a real
Display-local sort reorders the *displayed* rows from ``table_get_sort_specs``;
and a ``single``/``multi`` selection rides ``begin_multi_select`` with the
int-``SelectionUserData`` ↔ ``row_id`` translation the ``TableRowSelection``
arbiter owns. The selection is Hub-authoritative, but the storage is seeded from
the ``TableSelectionArbiter``'s *effective* set, not the raw
``elem.selected_row_ids``: through the gesture-to-re-push window the arbiter holds
the fired picks so a rapid second gesture accumulates instead of dropping the
first. A genuine user change fires ``RowSelectionChanged`` for the Hub to record
and re-push.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, final

from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.renderers.imgui.table_column_weights import ColumnWeights
from punt_lux.display.renderers.imgui.table_row_painter import Pair, TableRowPainter
from punt_lux.display.renderers.imgui.table_sort import TableSort
from punt_lux.protocol.elements.table import TableElement

if TYPE_CHECKING:
    from punt_lux.protocol.elements.table_flags import TableFlags

__all__ = ["ImGuiTableRenderer"]

_STRETCH = int(imgui.TableColumnFlags_.width_stretch.value)


@final
class ImGuiTableRenderer(LeafRenderer[TableElement]):
    """Paint a TableElement: native scroll, real sort, Hub-authoritative selection."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Paint the grid; fire ``RowSelectionChanged`` on a genuine user change."""
        elem = self._elem
        num_cols = len(elem.columns)
        if num_cols == 0:
            return
        table_id = f"##table_{elem.id}"
        height = self._reserve_height(
            elem.scroll_reserve_lines, imgui.get_text_line_height_with_spacing()
        )
        outer_size = imgui.ImVec2(0.0, height)
        if not imgui.begin_table(
            table_id, num_cols, self._table_flags(elem.flags), outer_size
        ):
            return
        try:
            self._setup_columns(elem)
            imgui.table_headers_row()
            pairs = self._ordered_pairs(elem)
            painter = TableRowPainter(self._factory.widget_state)
            if elem.selection_mode == "none":
                painter.paint_plain(pairs, num_cols)
            else:
                painter.paint_selectable(elem, pairs, num_cols)
        finally:
            imgui.end_table()

    # -- table setup --------------------------------------------------------

    @staticmethod
    def _table_flags(flags: TableFlags) -> int:
        """Return the ImGui table flags — the grid flags plus native scroll."""
        value = int(imgui.TableFlags_.scroll_y.value)
        if flags.borders:
            value |= int(imgui.TableFlags_.borders.value)
        if flags.row_bg:
            value |= int(imgui.TableFlags_.row_bg.value)
        if flags.resizable:
            value |= int(imgui.TableFlags_.resizable.value)
        if flags.sortable:
            value |= int(imgui.TableFlags_.sortable.value)
        return value

    @staticmethod
    def _reserve_height(reserve_lines: int, line_height: float) -> float:
        """Return the table's outer height for ``begin_table``.

        ``0`` means take the available height. A positive ``reserve_lines`` yields
        a *negative* height — ImGui reads that as available-minus-reserve — so the
        scroll region stops that many text lines short, leaving a following
        sibling (a detail panel) visible under the grid.
        """
        if reserve_lines <= 0:
            return 0.0
        return -reserve_lines * line_height

    def _setup_columns(self, elem: TableElement) -> None:
        """Declare each column with its stretch weight.

        Explicit ``column_widths`` win; otherwise the weights are proportioned to
        the widest cell text per column so an id column is not stretched as wide
        as a title, sparing the user a manual resize.
        """
        widths = elem.column_widths or ColumnWeights().for_content(
            elem.columns, elem.rows
        )
        for index, name in enumerate(elem.columns):
            weight = widths[index] if index < len(widths) else 1.0
            imgui.table_setup_column(name, _STRETCH, weight)
        imgui.table_setup_scroll_freeze(0, 1)  # keep the header row visible

    # -- sort ---------------------------------------------------------------

    def _ordered_pairs(self, elem: TableElement) -> list[Pair]:
        """Return ``(row_id, row)`` pairs in the current Display-local sort order."""
        pairs: list[Pair] = [(elem.row_id(row), row) for row in elem.rows]
        if not elem.flags.sortable:
            return pairs
        specs = self._sort_specs()
        return TableSort().order(pairs, specs) if specs else pairs

    @staticmethod
    def _sort_specs() -> tuple[tuple[int, bool], ...]:
        """Return ``(column_index, ascending)`` from ImGui's live sort specs."""
        # The binding returns None when nothing is sorted (the stub omits the
        # Optional), so widen before the guard rather than crash on ``.specs``.
        sort_specs = cast("imgui.TableSortSpecs | None", imgui.table_get_sort_specs())
        if sort_specs is None or sort_specs.specs_count == 0:
            return ()
        ascending = int(imgui.SortDirection.ascending)
        specs = (sort_specs.get_specs(i) for i in range(sort_specs.specs_count))
        return tuple(
            (spec.column_index, int(spec.sort_direction) == ascending) for spec in specs
        )
