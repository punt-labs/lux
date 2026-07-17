# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Render a ``TreeElement`` — a collapsible tree of recursive nodes.

Owns the whole tree paint surface: the node walk, the flat/indented
branch and leaf chrome, and the click emit that routes a node selection
back to the owning Hub. Split out of ``ElementRenderer`` so the general
element dispatch and the tree subsystem each stay one responsibility
(PY-IC-6). The node-click emit is injected, never reached back through a
dispatcher.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, ClassVar, Self, final

from imgui_bundle import imgui

from punt_lux.protocol import RemoteEventHandlerInvocation

if TYPE_CHECKING:
    from punt_lux.protocol.elements.layout import TreeElement
    from punt_lux.types import EmitEventFn

__all__ = ["TreeRenderer"]


@final
class TreeRenderer:
    """Paint a tree element, emitting a node-click event on selection."""

    _LEAF: ClassVar[int] = imgui.TreeNodeFlags_.leaf.value
    _NO_PUSH: ClassVar[int] = imgui.TreeNodeFlags_.no_tree_push_on_open.value

    _emit_event: EmitEventFn

    def __new__(cls, emit_event: EmitEventFn) -> Self:
        self = super().__new__(cls)
        self._emit_event = emit_event
        return self

    def render(self, elem: TreeElement) -> None:
        """Paint the tree's optional label, then each top-level node."""
        eid = elem.id
        nodes = elem.nodes
        flat = elem.flat

        if elem.label:
            imgui.text(elem.label)
        for i, node in enumerate(nodes):
            self._render_node(node, f"{eid}_{i}", eid, flat=flat)

    def _render_node(
        self,
        node: dict[str, Any],
        node_id: str,
        tree_id: str,
        *,
        flat: bool = False,
    ) -> None:
        """Paint one node and recurse into its children."""
        label: str = node.get("label", "")
        children: list[dict[str, Any]] = node.get("children", [])

        if children:
            if flat:
                opened = imgui.tree_node_ex(f"{label}##{node_id}", self._NO_PUSH)
            else:
                opened = imgui.tree_node(f"{label}##{node_id}")
            if imgui.is_item_clicked():
                self._emit_node_click(tree_id, node_id, label)
            if opened:
                for i, child in enumerate(children):
                    self._render_node(child, f"{node_id}_{i}", tree_id, flat=flat)
                if not flat:
                    imgui.tree_pop()
        else:
            if flat:
                selected = False
                clicked, _ = imgui.selectable(f"{label}##{node_id}", selected)
                if clicked:
                    self._emit_node_click(tree_id, node_id, label)
            else:
                imgui.tree_node_ex(f"{label}##{node_id}", self._LEAF | self._NO_PUSH)
                if imgui.is_item_clicked():
                    self._emit_node_click(tree_id, node_id, label)

    def _emit_node_click(self, tree_id: str, node_id: str, label: str) -> None:
        """Route a node selection back to the owning Hub as a remote event."""
        self._emit_event(
            RemoteEventHandlerInvocation(
                element_id=tree_id,
                action="node_clicked",
                ts=time.time(),
                value={"node_id": node_id, "label": label},
            )
        )
