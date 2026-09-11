# pyright: reportMissingModuleSource=false
"""ImGuiTreeRenderer — Renderer-Protocol adapter for ``TreeElement``.

A display-only leaf: the optional heading, then each top-level ``TreeNode``
and its subtree. ``flat`` toggles branches inline (``NoTreePushOnOpen``) and
renders leaves as selectable items. Node expansion is Display-local ImGui
view state; the tree carries no interaction, so the walk is a pure paint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, final

from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.protocol.elements.tree import TreeElement

if TYPE_CHECKING:
    from punt_lux.protocol.elements.tree_node import TreeNode

__all__ = ["ImGuiTreeRenderer"]


@final
class ImGuiTreeRenderer(LeafRenderer[TreeElement]):
    """Paint a TreeElement's heading and recursive nodes + the shared tooltip."""

    _LEAF: ClassVar[int] = imgui.TreeNodeFlags_.leaf.value
    _NO_PUSH: ClassVar[int] = imgui.TreeNodeFlags_.no_tree_push_on_open.value

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Draw the tree under a per-element id scope, then heading and nodes.

        An anonymous element (id == "") falls back to object identity so two
        same-labelled anonymous trees don't share ImGui expansion state.
        """
        elem = self._elem
        imgui.push_id(elem.id or f"anon-{id(elem)}")
        try:
            if elem.label:
                imgui.text(elem.label)
            for i, node in enumerate(elem.nodes):
                self._paint_node(node, f"{elem.id}_{self._node_key(node, i)}")
        finally:
            imgui.pop_id()

    def _paint_node(self, node: TreeNode, node_id: str) -> None:
        """Paint one node and recurse into its children."""
        flat = self._elem.flat
        if node.children:
            if flat:
                opened = imgui.tree_node_ex(f"{node.label}##{node_id}", self._NO_PUSH)
            else:
                opened = imgui.tree_node(f"{node.label}##{node_id}")
            if opened:
                for i, child in enumerate(node.children):
                    self._paint_node(child, f"{node_id}_{self._node_key(child, i)}")
                if not flat:
                    imgui.tree_pop()
        elif flat:
            imgui.selectable(f"{node.label}##{node_id}", False)  # noqa: FBT003
        else:
            imgui.tree_node_ex(f"{node.label}##{node_id}", self._LEAF | self._NO_PUSH)

    @staticmethod
    def _node_key(node: TreeNode, index: int) -> str:
        """Stable ``id`` when set (so expand state follows a reorder), else position."""
        return f"id:{node.id}" if node.id else f"pos:{index}"
