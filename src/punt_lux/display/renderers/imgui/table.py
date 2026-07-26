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
from punt_lux.display.renderers.imgui.table_row_arbiter import TableSelectionArbiter
from punt_lux.display.renderers.imgui.table_selection import TableRowSelection
from punt_lux.display.renderers.imgui.table_sort import TableSort
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.selection_interaction import RowSelectionChanged
from punt_lux.protocol.elements.table import TableElement

if TYPE_CHECKING:
    from collections.abc import Iterator

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

    @staticmethod
    def _visible_indices(count: int, *, ensure: int = -1) -> Iterator[int]:
        """Yield the row indices ImGui's list clipper leaves visible.

        The clipper draws only the ~screenful of rows in view (order tens), so a
        10k-row grid paints tens of rows a frame, not all of them. ``ensure``
        forces one index (the multi-select range source) to stay unclipped so a
        shift-range drag anchored off-screen still resolves.
        """
        clipper = imgui.ListClipper()
        clipper.begin(count)
        if ensure != -1:
            clipper.include_item_by_index(ensure)
        while clipper.step():
            yield from range(clipper.display_start, clipper.display_end)

    def _paint_plain(self, pairs: list[_Pair], num_cols: int) -> None:
        """Paint a display-only grid — no selection affordance (mode ``none``)."""
        for index in self._visible_indices(len(pairs)):
            _row_id, row = pairs[index]
            imgui.table_next_row()
            for col in range(num_cols):
                imgui.table_next_column()
                imgui.text(self._cell_text(row, col))

    def _paint_selectable(
        self, elem: TableElement, pairs: list[_Pair], num_cols: int
    ) -> None:
        """Paint a selectable grid and fire on a genuine user selection change."""
        display_ids = tuple(row_id for row_id, _ in pairs)
        arbiter = TableSelectionArbiter(self._factory.widget_state, elem.id)
        seed = arbiter.effective_selection(elem.selected_row_ids)
        storage = self._seeded_storage(display_ids, seed)
        flags = self._multi_select_flags(elem.selection_mode)
        io = imgui.begin_multi_select(flags, storage.size, len(display_ids))
        storage.apply_requests(io)
        # end_multi_select must run even if a row paint raises, or the ImGui
        # multi-select scope stays open and the next frame is corrupt — the same
        # finally discipline begin_table/end_table has.
        try:
            self._paint_selectable_rows(pairs, num_cols, storage, io.range_src_item)
        finally:
            io = imgui.end_multi_select()
            storage.apply_requests(io)
        self._fire_if_changed(elem, display_ids, seed, storage, io, arbiter)
        arbiter.record_honoured(elem.selected_row_ids)

    @staticmethod
    def _seeded_storage(
        display_ids: tuple[str, ...], seed: frozenset[str]
    ) -> imgui.SelectionBasicStorage:
        """Return a storage carrying the arbiter's effective selection.

        The scan is O(rows) — every display id is walked to find its index, the
        only place an id maps to its ImGui ``SelectionUserData`` — while the ImGui
        work is O(selected): a fresh storage defaults to unselected, so only the
        selected indices are set. The scan is a cheap set-membership loop, not a
        draw call, so it is orthogonal to the list clipper's O(visible) paint
        bound the 10k-row story rests on.
        """
        storage = imgui.SelectionBasicStorage()
        for index, row_id in enumerate(display_ids):
            if row_id in seed:
                storage.set_item_selected(index, selected=True)
        return storage

    @staticmethod
    def _multi_select_flags(mode: str) -> int:
        """Return the multi-select scope flags for ``single`` or ``multi``.

        ``box_select1d`` (drag a rubber-band over a range) is a multi-select
        affordance only; a single-select scope gets ``single_select`` instead, so
        a rubber-band drag never toggles rows a single-select table can't hold.
        """
        value = int(imgui.MultiSelectFlags_.clear_on_escape.value)
        if mode == "single":
            value |= int(imgui.MultiSelectFlags_.single_select.value)
        else:
            value |= int(imgui.MultiSelectFlags_.box_select1d.value)
        return value

    def _paint_selectable_rows(
        self,
        pairs: list[_Pair],
        num_cols: int,
        storage: imgui.SelectionBasicStorage,
        range_src: int,
    ) -> None:
        """Paint each visible row as a span-all-columns selectable, index-tagged.

        Only the clipper's visible window is painted; ``range_src`` (the ImGui
        multi-select range source) is force-included so a shift-range drag whose
        anchor scrolled out of view still resolves. The tag is the row's absolute
        display-order index, so the index-to-row_id translation is unaffected by
        which rows the clipper drew.
        """
        for index in self._visible_indices(len(pairs), ensure=range_src):
            _row_id, row = pairs[index]
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
        seed: frozenset[str],
        storage: imgui.SelectionBasicStorage,
        io: imgui.MultiSelectIO,
        arbiter: TableSelectionArbiter,
    ) -> None:
        """Fire ``RowSelectionChanged`` when the gesture changed the seeded set.

        The change is judged only against the *representable* part of the seed —
        ``seed`` intersected with this frame's ``display_ids``. A pending id the
        Hub filtered out of the rows cannot be seeded into ImGui's storage, so
        comparing against the full seed would mismatch it every frame and fire
        spuriously (the ghost class, entering through the pending set). Those
        non-representable ids survive in the arbiter's pending for restore, but
        never participate in the fire decision.
        """
        representable = seed & frozenset(display_ids)
        translator = TableRowSelection(display_ids)
        selected = frozenset(
            index for index in range(len(display_ids)) if storage.contains(index)
        )
        new_ids = translator.ids_for(selected)
        if not translator.is_user_change(new_ids, representable):
            return
        anchor = translator.anchor_for(io.range_src_item, new_ids)
        if elem.flags.copy_id and anchor:
            # Click-to-copy the id: the anchor is the last-interacted row's
            # key value (the row_id), mirroring the legacy copy_id feature.
            imgui.set_clipboard_text(anchor)
        # Keep the non-representable pending ids (hidden by a filter) alongside
        # the new visible picks, so they survive the re-push window for restore.
        arbiter.note_pending(new_ids | (seed - frozenset(display_ids)))
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
