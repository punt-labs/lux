"""``TreeValidator`` — the tree's selection self-validation (DES-039).

Mirrors ``TableValidator``: node well-formedness (a non-mapping node, a
missing ``label``) is already rejected at the wire boundary by
``TreeNode.decode_all``, so nothing is left for ``validate()`` to report about
node *shape*. What remains — and what this class reports — is selection
*content*, exactly the class of error ``TableValidator`` reports for a
selectable grid: a selected id naming no live node, a single-mode selection
holding more than one id, an anchor that is not itself selected, and a
duplicate non-empty id among the live nodes (which would make a selected id
ambiguous). A display-only (``none``-mode) tree has none of these
constraints — selection machinery does not exist for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.validation import ValidationError

if TYPE_CHECKING:
    from punt_lux.protocol.elements.tree import TreeElement

__all__ = ["TreeValidator"]


@final
class TreeValidator:
    """Collect a ``TreeElement``'s self-validation errors."""

    _elem: TreeElement
    __slots__ = ("_elem",)

    def __new__(cls, elem: TreeElement) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        return self

    def errors(self) -> tuple[ValidationError, ...]:
        """Return the selection-only errors; empty for a display-only tree."""
        if self._elem.selection_mode == "none":
            return ()
        errors = list(self._duplicate_id_errors())
        selected = self._elem.selected_node_ids
        live = frozenset(id_ for node in self._elem.nodes for id_ in node.ids())
        errors.extend(
            self._error(f"selected id {node_id!r} names no node")
            for node_id in sorted(selected - live)
        )
        if self._elem.selection_mode == "single" and len(selected) > 1:
            errors.append(self._error("single-select holds more than one node"))
        anchor = self._elem.anchor_node_id
        if anchor and anchor not in selected:
            errors.append(self._error(f"anchor {anchor!r} is not a selected node"))
        return tuple(errors)

    def _duplicate_id_errors(self) -> tuple[ValidationError, ...]:
        """Return one error per non-empty id shared by more than one node."""
        errors: list[ValidationError] = []
        seen: set[str] = set()
        for node in self._elem.nodes:
            for node_id in node.ids():
                if node_id in seen:
                    errors.append(self._error(f"duplicate node id {node_id!r}"))
                seen.add(node_id)
        return tuple(errors)

    def _error(self, message: str) -> ValidationError:
        """Build a tree ValidationError carrying the element's identity."""
        return ValidationError(
            element_id=self._elem.id, element_kind=self._elem.kind, message=message
        )
