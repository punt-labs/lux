"""ImGuiTableRenderer — copy_id click-to-copy and the multi-select finally guard.

The full grid paint is Level-6 visual; these mock the ``imgui`` module to verify
the two behaviors that would otherwise silently regress: copy_id copies the
anchor's key value on a user change, and end_multi_select runs even if a row
paint raises (so the ImGui scope never stays open).
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.table import ImGuiTableRenderer
from punt_lux.protocol.elements.table import TableElement
from punt_lux.protocol.elements.table_flags import TableFlags


def _renderer(elem: TableElement) -> ImGuiTableRenderer:
    return ImGuiTableRenderer(elem, cast("ImGuiRendererFactory", MagicMock()))


def _storage(selected_indices: set[int]) -> MagicMock:
    def contains(index: int) -> bool:
        return index in selected_indices

    storage = MagicMock()
    storage.contains.side_effect = contains
    return storage


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
        elem, display_ids, frozenset(), _storage({0, 2}), io
    )
    imgui.set_clipboard_text.assert_called_once_with("c")


def test_copy_id_off_does_not_touch_the_clipboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imgui = MagicMock()
    monkeypatch.setattr("punt_lux.display.renderers.imgui.table.imgui", imgui)
    elem = TableElement(id="t", columns=("ID",), rows=(("a",),), selection_mode="multi")
    io = MagicMock(range_src_item=0)
    _renderer(elem)._fire_if_changed(elem, ("a",), frozenset(), _storage({0}), io)
    imgui.set_clipboard_text.assert_not_called()


def test_end_multi_select_runs_even_when_a_row_paint_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imgui = MagicMock()
    imgui.table_next_row.side_effect = RuntimeError("paint blew up")
    monkeypatch.setattr("punt_lux.display.renderers.imgui.table.imgui", imgui)
    elem = TableElement(id="t", columns=("ID",), rows=(("a",),), selection_mode="multi")
    with pytest.raises(RuntimeError, match="paint blew up"):
        _renderer(elem)._paint_selectable(elem, [("a", ("a",))], 1)
    # The scope was still balanced despite the raise.
    imgui.end_multi_select.assert_called_once()
