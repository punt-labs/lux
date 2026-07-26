"""ImGuiTableRenderer — copy_id, the finally guard, and list-clipper paint.

The full grid paint is Level-6 visual; these mock the ``imgui`` module to verify
the behaviors that would otherwise silently regress: copy_id copies the anchor's
key value on a user change, end_multi_select runs even if a row paint raises (so
the ImGui scope never stays open), and both row loops paint only the clipper's
visible window (so a 10k-row grid draws tens of rows, not all of them).
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest
from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.table import ImGuiTableRenderer
from punt_lux.display.renderers.imgui.table_row_arbiter import TableSelectionArbiter
from punt_lux.domain.selection_interaction import RowSelectionChanged
from punt_lux.protocol.elements.table import TableElement
from punt_lux.protocol.elements.table_flags import TableFlags
from punt_lux.scene.widget_state import WidgetState


def _renderer(elem: TableElement) -> ImGuiTableRenderer:
    return ImGuiTableRenderer(elem, cast("ImGuiRendererFactory", MagicMock()))


def _arbiter(elem: TableElement) -> TableSelectionArbiter:
    return TableSelectionArbiter(WidgetState(), elem.id)


def _storage(selected_indices: set[int]) -> MagicMock:
    def contains(index: int) -> bool:
        return index in selected_indices

    storage = MagicMock()
    storage.contains.side_effect = contains
    return storage


def _imgui_with_clipper(visible: int) -> MagicMock:
    """Return a mock ``imgui`` whose ListClipper yields one window of ``visible``.

    Without this the mock clipper's ``step()`` returns a truthy MagicMock forever
    and the paint loop spins; here ``step`` yields True once (rows 0..visible)
    then False, so the loop draws exactly ``visible`` rows.
    """
    imgui = MagicMock()
    clipper = imgui.ListClipper.return_value
    clipper.step.side_effect = [True, False]
    clipper.display_start = 0
    clipper.display_end = visible
    return imgui


def test_copy_id_copies_the_anchor_key_on_a_user_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imgui = MagicMock()
    monkeypatch.setattr("punt_lux.display.renderers.imgui.table.imgui", imgui)
    elem = TableElement(
        id="t",
        columns=("ID",),
        rows=(("a",), ("b",), ("c",)),
        flags=TableFlags(copy_id=True),
        selection_mode="multi",
    )
    display_ids = ("a", "b", "c")
    io = MagicMock(range_src_item=2)  # last-interacted row -> anchor "c"
    _renderer(elem)._fire_if_changed(
        elem, display_ids, frozenset(), _storage({0, 2}), io, _arbiter(elem)
    )
    imgui.set_clipboard_text.assert_called_once_with("c")


def test_copy_id_off_does_not_touch_the_clipboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imgui = MagicMock()
    monkeypatch.setattr("punt_lux.display.renderers.imgui.table.imgui", imgui)
    elem = TableElement(id="t", columns=("ID",), rows=(("a",),), selection_mode="multi")
    io = MagicMock(range_src_item=0)
    _renderer(elem)._fire_if_changed(
        elem, ("a",), frozenset(), _storage({0}), io, _arbiter(elem)
    )
    imgui.set_clipboard_text.assert_not_called()


def test_no_spurious_fire_for_a_non_representable_pending_id() -> None:
    # PR #283 HIGH: the seed carries B, a pending id the Hub filter removed from
    # the rows, so display_ids is just A. B cannot be seeded into the storage; the
    # fire must compare only the representable part (seed ∩ display_ids = {A})
    # against the storage's {A} -> no change, no fire. Comparing the full seed
    # would mismatch B every frame and fire spuriously (the ghost class).
    elem = TableElement(id="t", columns=("ID",), rows=(("a",),), selection_mode="multi")
    fired: list[RowSelectionChanged] = []
    elem.add_handler(RowSelectionChanged, fired.append)
    _renderer(elem)._fire_if_changed(
        elem,
        ("a",),
        frozenset({"a", "b"}),  # b is not in display_ids
        _storage({0}),
        MagicMock(range_src_item=0),
        _arbiter(elem),
    )
    assert fired == []


def test_a_genuine_change_still_fires_with_a_hidden_pending_id() -> None:
    # display_ids {A, C}, seed {A, B} (B hidden). The user adds C: storage {A, C}
    # vs representable {A} -> a real change, so it fires the visible picks {A, C}.
    elem = TableElement(
        id="t", columns=("ID",), rows=(("a",), ("c",)), selection_mode="multi"
    )
    fired: list[RowSelectionChanged] = []
    elem.add_handler(RowSelectionChanged, fired.append)
    _renderer(elem)._fire_if_changed(
        elem,
        ("a", "c"),
        frozenset({"a", "b"}),
        _storage({0, 1}),
        MagicMock(range_src_item=1),
        _arbiter(elem),
    )
    assert len(fired) == 1
    assert set(fired[0].row_ids) == {"a", "c"}


def test_seeded_storage_sets_only_the_selected_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The ImGui work is O(selected): a fresh storage defaults to unselected, so
    # only the selected display indices are set (b at index 1 is skipped).
    imgui_mock = MagicMock()
    monkeypatch.setattr("punt_lux.display.renderers.imgui.table.imgui", imgui_mock)
    ImGuiTableRenderer._seeded_storage(("a", "b", "c"), frozenset({"a", "c"}))
    storage = imgui_mock.SelectionBasicStorage.return_value
    set_indices = [call.args[0] for call in storage.set_item_selected.call_args_list]
    assert set_indices == [0, 2]


def test_reserve_height_is_zero_when_no_reserve() -> None:
    assert ImGuiTableRenderer._reserve_height(0, 20.0) == 0.0
    assert ImGuiTableRenderer._reserve_height(-3, 20.0) == 0.0


def test_reserve_height_is_negative_available_minus_reserve() -> None:
    # A positive reserve yields a negative outer height — ImGui reads that as
    # available-minus-reserve, so the grid stops short and the detail stays visible.
    assert ImGuiTableRenderer._reserve_height(8, 20.0) == -160.0


def test_box_select_is_a_multi_only_affordance() -> None:
    # box_select1d (rubber-band a range) belongs to multi-select only; a
    # single-select scope must not enable it, and gets single_select instead.
    box = int(imgui.MultiSelectFlags_.box_select1d.value)
    single = int(imgui.MultiSelectFlags_.single_select.value)
    multi_flags = ImGuiTableRenderer._multi_select_flags("multi")
    single_flags = ImGuiTableRenderer._multi_select_flags("single")
    assert multi_flags & box, "multi-select enables box-select"
    assert not single_flags & box, "single-select must not enable box-select"
    assert single_flags & single, "single-select sets the single_select flag"
    assert not multi_flags & single


def test_plain_grid_paints_only_the_clipper_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A 1000-row display-only grid must paint only the clipper's visible window,
    # not all 1000 rows — the design's 10k-row position depends on it.
    imgui = _imgui_with_clipper(visible=30)
    monkeypatch.setattr("punt_lux.display.renderers.imgui.table.imgui", imgui)
    rows = tuple((str(i),) for i in range(1000))
    elem = TableElement(id="t", columns=("ID",), rows=rows)
    pairs: list[tuple[str, tuple[object, ...]]] = [
        (str(i), (str(i),)) for i in range(1000)
    ]
    _renderer(elem)._paint_plain(pairs, 1)
    imgui.ListClipper.return_value.begin.assert_called_once_with(1000)
    assert imgui.table_next_row.call_count == 30


def test_selectable_grid_clips_and_pins_the_range_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The selectable loop clips too, and force-includes the range source so a
    # shift-range drag whose anchor scrolled off screen still resolves.
    imgui = _imgui_with_clipper(visible=25)
    monkeypatch.setattr("punt_lux.display.renderers.imgui.table.imgui", imgui)
    elem = TableElement(
        id="t",
        columns=("ID",),
        rows=tuple((str(i),) for i in range(1000)),
        selection_mode="multi",
    )
    pairs: list[tuple[str, tuple[object, ...]]] = [
        (str(i), (str(i),)) for i in range(1000)
    ]
    _renderer(elem)._paint_selectable_rows(pairs, 1, _storage(set()), 7)
    imgui.ListClipper.return_value.include_item_by_index.assert_called_once_with(7)
    assert imgui.table_next_row.call_count == 25


def test_end_multi_select_runs_even_when_a_row_paint_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imgui = _imgui_with_clipper(visible=1)
    imgui.table_next_row.side_effect = RuntimeError("paint blew up")
    monkeypatch.setattr("punt_lux.display.renderers.imgui.table.imgui", imgui)
    elem = TableElement(id="t", columns=("ID",), rows=(("a",),), selection_mode="multi")
    with pytest.raises(RuntimeError, match="paint blew up"):
        _renderer(elem)._paint_selectable(elem, [("a", ("a",))], 1)
    # The scope was still balanced despite the raise.
    imgui.end_multi_select.assert_called_once()
