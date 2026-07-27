# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""TableRowPainter — the grid's row bodies and the selection-fire decision.

Split from ``ImGuiTableRenderer``, which keeps the table frame (columns, sort,
scroll reserve) and delegates the row interior here: the list-clipped plain and
selectable row loops, the ``begin_multi_select`` storage seeding, and the fire
decision. A genuine user change fires ``RowSelectionChanged`` (for the Hub to
record and re-push); a re-click on the row that is already the whole selection
copies its id without firing (legacy click-again-to-copy). The int-
``SelectionUserData`` ↔ ``row_id`` translation is the ``TableRowSelection``
arbiter's; the effective seed across the gesture-to-re-push window is the
``TableSelectionArbiter``'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.table_row_arbiter import TableSelectionArbiter
from punt_lux.display.renderers.imgui.table_selection import TableRowSelection
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.selection_interaction import RowSelectionChanged

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.protocol.elements.table import TableElement
    from punt_lux.scene.widget_state import WidgetState

__all__ = ["Pair", "TableRowPainter"]

_SPAN_ALL = int(imgui.SelectableFlags_.span_all_columns.value)
_DISPLAY = "__display__"

type Pair = tuple[str, tuple[object, ...]]


@final
class TableRowPainter:
    """Paint a grid's row bodies and fire ``RowSelectionChanged`` on a user change."""

    _widget_state: WidgetState
    __slots__ = ("_widget_state",)

    def __new__(cls, widget_state: WidgetState) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
        return self

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

    def paint_plain(self, pairs: list[Pair], num_cols: int) -> None:
        """Paint a display-only grid — no selection affordance (mode ``none``)."""
        for index in self._visible_indices(len(pairs)):
            _row_id, row = pairs[index]
            imgui.table_next_row()
            for col in range(num_cols):
                imgui.table_next_column()
                imgui.text(self._cell_text(row, col))

    def paint_selectable(
        self, elem: TableElement, pairs: list[Pair], num_cols: int
    ) -> None:
        """Paint a selectable grid and fire on a genuine user selection change."""
        display_ids = tuple(row_id for row_id, _ in pairs)
        arbiter = TableSelectionArbiter(self._widget_state, elem.id)
        seed = arbiter.effective_selection(elem.selected_row_ids)
        storage = self._seeded_storage(display_ids, seed)
        flags = self._multi_select_flags(elem.selection_mode)
        clicked_id = ""
        io = imgui.begin_multi_select(flags, storage.size, len(display_ids))
        storage.apply_requests(io)
        # end_multi_select must run even if a row paint raises, or the ImGui
        # multi-select scope stays open and the next frame is corrupt — the same
        # finally discipline begin_table/end_table has.
        try:
            clicked_id = self._paint_selectable_rows(
                pairs, num_cols, storage, io.range_src_item
            )
        finally:
            io = imgui.end_multi_select()
            storage.apply_requests(io)
        self._fire_if_changed(elem, display_ids, seed, storage, io, arbiter, clicked_id)
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
        pairs: list[Pair],
        num_cols: int,
        storage: imgui.SelectionBasicStorage,
        range_src: int,
    ) -> str:
        """Paint each visible row as a span-all-columns selectable, index-tagged.

        Only the clipper's visible window is painted; ``range_src`` (the ImGui
        multi-select range source) is force-included so a shift-range drag whose
        anchor scrolled out of view still resolves. The tag is the row's absolute
        display-order index, so the index-to-row_id translation is unaffected by
        which rows the clipper drew. Returns the id of the row clicked this frame
        (or ``""``), so the caller can honour a same-row re-click copy_id — a click
        that changes no selection set.
        """
        clicked_id = ""
        for index in self._visible_indices(len(pairs), ensure=range_src):
            row_id, row = pairs[index]
            imgui.table_next_row()
            imgui.table_next_column()
            imgui.set_next_item_selection_user_data(index)
            if imgui.selectable(
                f"{self._cell_text(row, 0)}##row_{index}",
                storage.contains(index),
                _SPAN_ALL,
            ):
                clicked_id = row_id
            for col in range(1, num_cols):
                imgui.table_next_column()
                imgui.text(self._cell_text(row, col))
        return clicked_id

    def _fire_if_changed(
        self,
        elem: TableElement,
        display_ids: tuple[str, ...],
        seed: frozenset[str],
        storage: imgui.SelectionBasicStorage,
        io: imgui.MultiSelectIO,
        arbiter: TableSelectionArbiter,
        clicked_id: str,
    ) -> None:
        """Fire ``RowSelectionChanged`` when the gesture changed the seeded set.

        The change is judged only against the *representable* part of the seed —
        ``seed`` intersected with this frame's ``display_ids``. A pending id the
        Hub filtered out of the rows cannot be seeded into ImGui's storage, so
        comparing against the full seed would mismatch it every frame and fire
        spuriously (the ghost class, entering through the pending set). Those
        non-representable ids survive in the arbiter's pending for restore, but
        never participate in the fire decision.

        A click that changes no set still copies the row id when it re-clicks the
        row that IS the whole selection (legacy click-again-to-copy) — a
        display-local convenience, so nothing fires authoritatively.
        """
        representable = seed & frozenset(display_ids)
        translator = TableRowSelection(display_ids)
        selected = frozenset(
            index for index in range(len(display_ids)) if storage.contains(index)
        )
        new_ids = translator.ids_for(selected)
        if not translator.is_user_change(new_ids, representable):
            if elem.flags.copy_id and self._is_same_row_reclick(
                clicked_id, representable
            ):
                imgui.set_clipboard_text(clicked_id)
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
    def _is_same_row_reclick(clicked_id: str, representable: frozenset[str]) -> bool:
        """Return whether the click landed on the row that is already the whole
        selection — the set did not change, but a copy_id re-click still copies."""
        return clicked_id != "" and representable == frozenset({clicked_id})

    @staticmethod
    def _cell_text(row: tuple[object, ...], col: int) -> str:
        """Return the printable text for ``row``'s cell in column ``col``."""
        if not 0 <= col < len(row):
            return ""
        cell = row[col]
        return "" if cell is None else str(cell)
