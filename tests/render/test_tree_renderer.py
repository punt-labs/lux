"""TreeRenderer paints a tree and emits node-click events on selection.

The renderer under test is real; only the ImGui backend is faked (a mock
at the render boundary). Node-click emit is asserted against the injected
``emit_event`` — behaviour identical to the pre-extraction inline body.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.display.renderers.leaf_widget_renderer import LeafWidgetRenderer
from punt_lux.display.renderers.tree_renderer import TreeRenderer
from punt_lux.protocol.elements.layout import TreeElement

if TYPE_CHECKING:
    import pytest

    from punt_lux.protocol.messages.remote_invocation import (
        RemoteEventHandlerInvocation,
    )


def _fake_imgui(*, clicked: bool = False, opened: bool = True) -> MagicMock:
    """Build a fake ImGui module recording the tree paint calls."""
    imgui = MagicMock()
    imgui.tree_node.return_value = opened
    imgui.tree_node_ex.return_value = opened
    imgui.selectable.return_value = (clicked, False)
    imgui.is_item_clicked.return_value = clicked
    imgui.TreeNodeFlags_.no_tree_push_on_open.value = 1
    imgui.TreeNodeFlags_.leaf.value = 2
    return imgui


def _patch(monkeypatch: pytest.MonkeyPatch, imgui: MagicMock) -> None:
    monkeypatch.setattr("punt_lux.display.renderers.tree_renderer.imgui", imgui)


def test_tree_renderer_satisfies_leaf_widget_protocol() -> None:
    assert isinstance(TreeRenderer(lambda _msg: None), LeafWidgetRenderer)


def test_render_paints_label_then_walks_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    imgui = _fake_imgui(clicked=False)
    _patch(monkeypatch, imgui)
    events: list[RemoteEventHandlerInvocation] = []
    tree = TreeElement(
        id="tr",
        label="Root",
        nodes=[{"label": "A", "children": [{"label": "A1"}]}],
    )

    TreeRenderer(events.append).render(tree)

    imgui.text.assert_called_once_with("Root")
    assert events == []  # nothing clicked → no emit


def test_render_emits_node_click_for_branch_and_leaf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imgui = _fake_imgui(clicked=True, opened=True)
    _patch(monkeypatch, imgui)
    events: list[RemoteEventHandlerInvocation] = []
    tree = TreeElement(
        id="tr",
        nodes=[{"label": "A", "children": [{"label": "A1"}]}],
    )

    TreeRenderer(events.append).render(tree)

    assert [e.action for e in events] == ["node_clicked", "node_clicked"]
    assert events[0].element_id == "tr"
    assert events[0].value == {"node_id": "tr_0", "label": "A"}
    assert events[1].value == {"node_id": "tr_0_0", "label": "A1"}


def test_flat_leaf_emits_via_selectable(monkeypatch: pytest.MonkeyPatch) -> None:
    imgui = _fake_imgui(clicked=True)
    _patch(monkeypatch, imgui)
    events: list[RemoteEventHandlerInvocation] = []
    tree = TreeElement(id="tr", nodes=[{"label": "Leaf"}], flat=True)

    TreeRenderer(events.append).render(tree)

    imgui.selectable.assert_called_once_with("Leaf##tr_0", False)
    assert [e.value for e in events] == [{"node_id": "tr_0", "label": "Leaf"}]


def test_empty_label_is_not_painted(monkeypatch: pytest.MonkeyPatch) -> None:
    imgui = _fake_imgui()
    _patch(monkeypatch, imgui)

    TreeRenderer(lambda _msg: None).render(TreeElement(id="tr", nodes=[]))

    imgui.text.assert_not_called()
