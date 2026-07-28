"""LeafRenderer records each leaf's geometry from the one place both paths reach.

The template ``paint`` paints the widget inside the geometry ``measuring`` group
(which records the leaf's rect when the group closes), then runs the tooltip pass
*after* the group closes — so ``is_item_hovered`` covers the whole multi-item leaf,
not just its last painted item. Recording lives on the adapter, the single point
``elem.render()`` and ``_render_via_factory`` both call, so a top-level or
ABC-nested leaf is captured, not only a legacy-nested one. Three guards: the
record happens after the whole paint (so the group bounds it), the tooltip runs
after the group closes (so a multi-item leaf's hover covers the whole leaf), and
every leaf adapter the factory dispatches inherits the template, so no leaf kind
can be added without its geometry captured.

The leaf set the second guard covers is derived from the factory's own
``_DISPATCH`` table minus an explicit container allowlist, not a hand-kept list:
a new leaf kind added to ``_DISPATCH`` is auto-covered, and a new *container*
must be consciously added to the allowlist to be exempted — otherwise it lands in
the leaf set and fails the inheritance assertion.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Self, cast, final
from unittest.mock import MagicMock

import pytest

from punt_lux.display.renderers.imgui.collapsing_header import (
    ImGuiCollapsingHeaderRenderer,
)
from punt_lux.display.renderers.imgui.dialog import ImGuiDialogRenderer
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.group import ImGuiGroupRenderer
from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.renderers.imgui.modal import ImGuiModalRenderer
from punt_lux.display.renderers.imgui.split_pane import ImGuiSplitPaneRenderer
from punt_lux.display.renderers.imgui.tab_bar import ImGuiTabBarRenderer
from punt_lux.display.renderers.imgui.tree import ImGuiTreeRenderer
from punt_lux.display.renderers.imgui.window import ImGuiWindowRenderer
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.elements.tree import TreeElement
from punt_lux.protocol.elements.tree_node import TreeNode

if TYPE_CHECKING:
    from collections.abc import Generator

# The container adapters — the ones that open a surface and render children, not
# a single widget. They are exempt from the leaf-inheritance guard, and adding a
# new container here is the conscious act the derivation forces.
_CONTAINER_ADAPTERS: frozenset[type] = frozenset(
    {
        ImGuiWindowRenderer,
        ImGuiModalRenderer,
        ImGuiDialogRenderer,
        ImGuiGroupRenderer,
        ImGuiSplitPaneRenderer,
        ImGuiTabBarRenderer,
        ImGuiCollapsingHeaderRenderer,
    }
)

_DISPATCHED_ADAPTERS: frozenset[type] = frozenset(
    cast("type", adapter) for _, adapter in ImGuiRendererFactory._DISPATCH
)

# Every dispatched adapter that is not an allowlisted container is a leaf and must
# inherit the recording base — derived, so a new leaf kind cannot slip the guard.
_LEAF_ADAPTERS: list[type] = sorted(
    _DISPATCHED_ADAPTERS - _CONTAINER_ADAPTERS, key=lambda a: a.__name__
)
_SORTED_CONTAINERS: list[type] = sorted(_CONTAINER_ADAPTERS, key=lambda a: a.__name__)


class _CaptureSpy:
    """A geometry-capture stand-in whose ``measuring`` records the id on exit."""

    recorded: list[str]
    group_open: bool
    _order: list[str]
    __slots__ = ("_order", "group_open", "recorded")

    def __new__(cls, order: list[str]) -> Self:
        self = super().__new__(cls)
        self.recorded = []
        self.group_open = False
        self._order = order
        return self

    @contextmanager
    def measuring(self, element_id: str, kind: str) -> Generator[None]:
        _ = kind
        self.group_open = True
        try:
            yield
        finally:
            self.group_open = False
            self.recorded.append(element_id)
            self._order.append("record")


class _FactorySpy:
    """A factory stand-in exposing the geometry capture and a tooltip spy."""

    geometry: _CaptureSpy
    tooltipped: list[object]
    order: list[str]
    group_open_at_tooltip: bool
    __slots__ = ("geometry", "group_open_at_tooltip", "order", "tooltipped")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.order = []
        self.geometry = _CaptureSpy(self.order)
        self.tooltipped = []
        self.group_open_at_tooltip = True
        return self

    def apply_tooltip(self, elem: object) -> None:
        # Capture whether the measuring group is still open when the tooltip runs:
        # it must be closed, so is_item_hovered sees the whole group's last item.
        self.group_open_at_tooltip = self.geometry.group_open
        self.tooltipped.append(elem)
        self.order.append("tooltip")


@final
class _SpyLeaf(LeafRenderer[TextElement]):
    """A concrete leaf whose widget hook just records that it ran."""

    _order: list[str]
    __slots__ = ("_order",)

    def __new__(cls, elem: TextElement, factory: object, order: list[str]) -> Self:
        self = super().__new__(cls, elem, cast("ImGuiRendererFactory", factory))
        self._order = order
        return self

    def _paint_widget(self) -> None:
        self._order.append("widget")


def test_paint_records_the_group_then_applies_the_tooltip() -> None:
    factory = _FactorySpy()
    leaf = _SpyLeaf(TextElement(id="leaf-1", content="x"), factory, factory.order)

    leaf.paint()

    # The widget paints inside the measuring group; the rect records when the group
    # closes; only then does the tooltip pass run — so is_item_hovered sees the
    # whole group, not the last painted item, and cannot affect the recorded rect.
    assert factory.order == ["widget", "record", "tooltip"]
    assert factory.geometry.recorded == ["leaf-1"]
    assert len(factory.tooltipped) == 1
    assert factory.group_open_at_tooltip is False


def test_multi_node_tree_applies_its_tooltip_after_the_group_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real multi-node tree runs its tooltip against the closed group, not a node."""
    monkeypatch.setattr("punt_lux.display.renderers.imgui.tree.imgui", MagicMock())
    factory = _FactorySpy()
    tree = TreeElement(
        id="tr",
        tooltip="hint",
        nodes=(TreeNode(label="a"), TreeNode(label="b"), TreeNode(label="c")),
    )

    ImGuiTreeRenderer(tree, cast("ImGuiRendererFactory", factory)).paint()

    # The tooltip pass ran after the group closed, so its is_item_hovered covers
    # every node's extent rather than only the last node painted.
    assert factory.order == ["record", "tooltip"]
    assert factory.group_open_at_tooltip is False
    assert factory.tooltipped == [tree]


@pytest.mark.parametrize("adapter", _LEAF_ADAPTERS)
def test_every_leaf_adapter_inherits_the_recording_base(adapter: type) -> None:
    assert issubclass(adapter, LeafRenderer)


@pytest.mark.parametrize("container", _SORTED_CONTAINERS)
def test_container_allowlist_holds_only_dispatched_non_leaves(container: type) -> None:
    # The allowlist can only exempt a real, dispatched container: an entry that
    # left ``_DISPATCH`` or that is secretly a leaf (which would dodge the guard)
    # fails here, so the exemption list cannot rot or hide a leaf.
    assert container in _DISPATCHED_ADAPTERS
    assert not issubclass(container, LeafRenderer)
