"""``TreeNodesState`` — a tree's node data bundled with its reconciled selection.

Composes ``TreeNode`` (the value family) and ``TreeSelectionModel``
(Hub-authoritative selection) into the one piece of state ``TreeElement``
replaces atomically on a ``nodes`` or selection patch (PY-IC-1). Keeps
``TreeElement`` a thin composition root: the reconciliation and wire-decode
work that used to sit in ``TreeElement._set_nodes`` et al. lives here instead,
mirroring how ``TreeSelectionModel`` already isolates the selection verbs.

Immutable: every verb returns a *new* state rather than mutating in place —
the same rollback discipline ``TreeSelectionModel`` documents for
``Element.apply_patch``'s all-or-nothing shallow-``vars()`` snapshot.
"""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.elements.selection_wire import SelectionWire
from punt_lux.protocol.elements.tree_node import TreeNode
from punt_lux.protocol.elements.tree_selection_model import TreeSelectionModel

__all__ = ["TreeNodesState"]

_DEFAULT_SELECTION = TreeSelectionModel()


class TreeNodesState:
    """The node tree plus its reconciled selection, always replaced together."""

    _nodes: tuple[TreeNode, ...]
    _live_ids: frozenset[str]
    _selection: TreeSelectionModel

    def __new__(
        cls,
        *,
        nodes: tuple[TreeNode, ...] = (),
        selection: TreeSelectionModel = _DEFAULT_SELECTION,
    ) -> Self:
        self = super().__new__(cls)
        self._nodes = nodes
        self._selection = selection
        self._live_ids = TreeSelectionModel.live_ids(nodes)
        return self

    @property
    def nodes(self) -> tuple[TreeNode, ...]:
        """Return the top-level nodes, each a recursive ``TreeNode`` value."""
        return self._nodes

    @property
    def selection(self) -> TreeSelectionModel:
        """Return the composed selection model."""
        return self._selection

    def replaced_nodes(self, value: object) -> Self:
        """Decode ``value`` as the new node tree, reconciling the selection to it."""
        nodes = TreeNode.decode_all(value, "nodes")
        selection = self._selection.reconciled(TreeSelectionModel.live_ids(nodes))
        return type(self)(nodes=nodes, selection=selection)

    def selected_from_wire(self, value: object) -> Self:
        """Decode ``value`` as the new selection, intersected with the live ids."""
        wire_ids = SelectionWire.decode_ids(value, "selected_node_ids")
        ids = frozenset(wire_ids) & self._live_ids
        return type(self)(
            nodes=self._nodes, selection=self._selection.with_selection(ids)
        )

    def anchored(self, node_id: str) -> Self:
        """Return a state whose anchor is ``node_id``, if it names a selected node."""
        return type(self)(
            nodes=self._nodes, selection=self._selection.with_anchor(node_id)
        )

    def resolved_props(self) -> dict[str, object]:
        """Return nodes + selection view-state for ``TreeElement.resolved_props``."""
        return {
            "nodes": [node.to_dict() for node in self._nodes],
            **self._selection.resolved_props(),
        }
