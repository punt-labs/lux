# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""ImGuiTableRenderer — the ImGui adapter for the ABC basic grid.

A ``LeafRenderer``: it paints one widget (the grid) and has no child elements, so
``LeafRenderer`` records its geometry and runs the shared tooltip pass around the
paint. The grid renders in a native ImGui scroll region (no pager); a real
Display-local sort reorders the *displayed* rows from ``table_get_sort_specs``;
and a ``single``/``multi`` selection rides ``begin_multi_select`` with the
int-``SelectionUserData`` ↔ ``row_id`` translation the ``TableRowSelection``
arbiter owns. The selection is Hub-authoritative: the storage is seeded from
``elem.selected_row_ids`` each frame, and a genuine user change fires
``RowSelectionChanged`` for the Hub to record and re-push.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, final

from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.renderers.imgui.table_selection import TableRowSelection
from punt_lux.display.renderers.imgui.table_sort import TableSort
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.selection_interaction import RowSelectionChanged
from punt_lux.protocol.elements.table import TableElement

if TYPE_CHECKING:
    from punt_lux.protocol.elements.table_flags import TableFlags

__all__ = ["ImGuiTableRenderer"]

_STRETCH = int(imgui.TableColumnFlags_.width_stretch.value)
_SPAN_ALL = int(imgui.SelectableFlags_.span_all_columns.value)
_DISPLAY = "__display__"

type _Pair = tuple[str, tuple[object, ...]]


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
        if not imgui.begin_table(table_id, num_cols, self._table_flags(elem.flags)):
            return
        try:
            self._setup_columns(elem)
            imgui.table_headers_row()
            pairs = self._ordered_pairs(elem)
            if elem.selection_mode == "none":
                self._paint_plain(pairs, num_cols)
            else:
                self._paint_selectable(elem, pairs, num_cols)
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

    def _setup_columns(self, elem: TableElement) -> None:
        """Declare each column with its stretch weight (explicit or uniform)."""
        widths = elem.column_widths
        for index, name in enumerate(elem.columns):
            weight = widths[index] if index < len(widths) else 1.0
            imgui.table_setup_column(name, _STRETCH, weight)
        imgui.table_setup_scroll_freeze(0, 1)  # keep the header row visible

    # -- sort ---------------------------------------------------------------

    def _ordered_pairs(self, elem: TableElement) -> list[_Pair]:
        """Return ``(row_id, row)`` pairs in the current Display-local sort order."""
        pairs: list[_Pair] = [(elem.row_id(row), row) for row in elem.rows]
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

    # -- row painting -------------------------------------------------------

    def _paint_plain(self, pairs: list[_Pair], num_cols: int) -> None:
        """Paint a display-only grid — no selection affordance (mode ``none``)."""
        for _row_id, row in pairs:
            imgui.table_next_row()
            for col in range(num_cols):
                imgui.table_next_column()
                imgui.text(self._cell_text(row, col))

    def _paint_selectable(
        self, elem: TableElement, pairs: list[_Pair], num_cols: int
    ) -> None:
        """Paint a selectable grid and fire on a genuine user selection change."""
        display_ids = tuple(row_id for row_id, _ in pairs)
        authoritative = elem.selected_row_ids
        storage = self._seeded_storage(display_ids, authoritative)
        flags = self._multi_select_flags(elem.selection_mode)
        io = imgui.begin_multi_select(flags, storage.size, len(display_ids))
        storage.apply_requests(io)
        # end_multi_select must run even if a row paint raises, or the ImGui
        # multi-select scope stays open and the next frame is corrupt — the same
        # finally discipline begin_table/end_table has.
        try:
            self._paint_selectable_rows(pairs, num_cols, storage)
        finally:
            io = imgui.end_multi_select()
            storage.apply_requests(io)
        self._fire_if_changed(elem, display_ids, authoritative, storage, io)

    @staticmethod
    def _seeded_storage(
        display_ids: tuple[str, ...], authoritative: frozenset[str]
    ) -> imgui.SelectionBasicStorage:
        """Return a storage seeded from the Hub-authoritative selection this frame."""
        storage = imgui.SelectionBasicStorage()
        for index, row_id in enumerate(display_ids):
            storage.set_item_selected(index, row_id in authoritative)
        return storage

    @staticmethod
    def _multi_select_flags(mode: str) -> int:
        """Return the multi-select scope flags for ``single`` or ``multi``."""
        value = int(imgui.MultiSelectFlags_.clear_on_escape.value) | int(
            imgui.MultiSelectFlags_.box_select1d.value
        )
        if mode == "single":
            value |= int(imgui.MultiSelectFlags_.single_select.value)
        return value

    def _paint_selectable_rows(
        self,
        pairs: list[_Pair],
        num_cols: int,
        storage: imgui.SelectionBasicStorage,
    ) -> None:
        """Paint each row as a span-all-columns selectable tagged by its index."""
        for index, (_row_id, row) in enumerate(pairs):
            imgui.table_next_row()
            imgui.table_next_column()
            imgui.set_next_item_selection_user_data(index)
            imgui.selectable(
                f"{self._cell_text(row, 0)}##row_{index}",
                storage.contains(index),
                _SPAN_ALL,
            )
            for col in range(1, num_cols):
                imgui.table_next_column()
                imgui.text(self._cell_text(row, col))

    def _fire_if_changed(
        self,
        elem: TableElement,
        display_ids: tuple[str, ...],
        authoritative: frozenset[str],
        storage: imgui.SelectionBasicStorage,
        io: imgui.MultiSelectIO,
    ) -> None:
        """Fire ``RowSelectionChanged`` when the gesture changed the selection."""
        translator = TableRowSelection(display_ids)
        selected = frozenset(
            index for index in range(len(display_ids)) if storage.contains(index)
        )
        new_ids = translator.ids_for(selected)
        if not translator.is_user_change(new_ids, authoritative):
            return
        anchor = translator.anchor_for(io.range_src_item, new_ids)
        if elem.flags.copy_id and anchor:
            # Click-to-copy the id: the anchor is the last-interacted row's
            # key value (the row_id), mirroring the legacy copy_id feature.
            imgui.set_clipboard_text(anchor)
        elem.fire(
            RowSelectionChanged(
                scene_id=SceneId(_DISPLAY),
                element_id=ElementId(elem.id),
                owner_id=ClientId(_DISPLAY),
                row_ids=tuple(sorted(new_ids)),
                anchor=anchor,
            )
        )

    @staticmethod
    def _cell_text(row: tuple[object, ...], col: int) -> str:
        """Return the printable text for ``row``'s cell in column ``col``."""
        if not 0 <= col < len(row):
            return ""
        cell = row[col]
        return "" if cell is None else str(cell)
