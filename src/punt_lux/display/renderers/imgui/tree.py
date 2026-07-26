# pyright: reportMissingModuleSource=false
"""ImGuiTreeRenderer — Renderer-Protocol adapter for ``TreeElement``.

A display-only leaf that paints a collapsible tree directly: the optional
heading, then each top-level ``TreeNode`` and its subtree. ``flat`` toggles
branches inline (``NoTreePushOnOpen``) and renders leaves as selectable items —
an inline disclosure for tight horizontal space. Node expansion is Display-local
ImGui view state; the tree carries no interaction, so a node click routes
nowhere and the walk is a pure paint (fork, don't mix — the render logic lives
on the ABC path, not the legacy dispatch). ``LeafRenderer`` adds the shared
tooltip pass and the geometry capture around it.
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
        """Draw the tree's optional heading, then each top-level node."""
        elem = self._elem
        if elem.label:
            imgui.text(elem.label)
        for i, node in enumerate(elem.nodes):
            self._paint_node(node, f"{elem.id}_{i}", flat=elem.flat)

    def _paint_node(self, node: TreeNode, node_id: str, *, flat: bool) -> None:
        """Paint one node and recurse into its children."""
        if node.children:
            if flat:
                opened = imgui.tree_node_ex(f"{node.label}##{node_id}", self._NO_PUSH)
            else:
                opened = imgui.tree_node(f"{node.label}##{node_id}")
            if opened:
                for i, child in enumerate(node.children):
                    self._paint_node(child, f"{node_id}_{i}", flat=flat)
                if not flat:
                    imgui.tree_pop()
        elif flat:
            imgui.selectable(f"{node.label}##{node_id}", False)  # noqa: FBT003
        else:
            imgui.tree_node_ex(f"{node.label}##{node_id}", self._LEAF | self._NO_PUSH)
