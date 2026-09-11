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

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements.selection_wire import SelectionWire
from punt_lux.protocol.elements.tree_node import TreeNode
from punt_lux.protocol.elements.tree_selection_model import TreeSelectionModel

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["TreeNodesState"]

_DEFAULT_SELECTION = TreeSelectionModel()
_PATCH_ORDER: tuple[str, ...] = ("nodes", "selected_node_ids", "anchor_node_id")


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

    @staticmethod
    def reordered_patch(patch: Mapping[str, object]) -> dict[str, object]:
        """Return ``patch`` with any nodes/selection keys moved to the front.

        ``Element.apply_patch`` dispatches setters in the caller's dict
        order; the selection setters intersect against the *current* live-id
        cache, so a patch listing ``selected_node_ids``/``anchor_node_id``
        ahead of ``nodes`` would silently drop ids that only exist in the
        new tree. Reordering here removes that footgun regardless of the
        patch's own key order.
        """
        ordered = {k: patch[k] for k in _PATCH_ORDER if k in patch}
        ordered.update((k, v) for k, v in patch.items() if k not in ordered)
        return ordered

    def resolved_props(self) -> dict[str, object]:
        """Return nodes + selection view-state for ``TreeElement.resolved_props``."""
        return {
            "nodes": [TreeNode.to_dict(node) for node in self._nodes],
            **self._selection.resolved_props(),
        }
