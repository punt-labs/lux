"""Facade over the tree-selection collaborators, so ``tree.py`` imports one module.

``TreeElement`` composes ``TreeNodesState`` (nodes + reconciled selection),
which in turn composes ``TreeSelectionModel`` and ``SelectionWire``; selection
*content* is validated via ``TreeValidator``. Importing each of those
collaborators directly from ``tree.py`` pushes its own efferent coupling up by
one every time the tree-selection machinery gains another collaborator — this
facade absorbs that fan-out instead (PL-CU-1), so ``tree.py``'s own efferent
coupling stays flat as the selection machinery decomposes further, mirroring
how ``protocol/messages/_wiring.py`` absorbs the message-family fan-out for
``protocol/messages/__init__.py``.
"""

from __future__ import annotations

from punt_lux.protocol.elements.selection_wire import SelectionWire
from punt_lux.protocol.elements.tree_nodes_state import TreeNodesState
from punt_lux.protocol.elements.tree_selection_model import (
    SelectionMode,
    TreeSelectionModel,
)
from punt_lux.protocol.elements.tree_validation import TreeValidator

__all__ = [
    "SelectionMode",
    "SelectionWire",
    "TreeNodesState",
    "TreeSelectionModel",
    "TreeValidator",
]
