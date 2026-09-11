"""``TreeSelectionModel`` — the tree's private, immutable selection state.

Mirrors ``TableSelectionModel`` (protocol/elements/table_selection_model.py)
exactly, substituting stable ``TreeNode.id`` values for a table's ``row_id``.
Owned by ``TreeElement`` (composition, PY-IC-1); nothing outside the tree
constructs it or calls its verbs. It holds the selection *mode*, the selected
node *id set*, and the *anchor* — the last-interacted node a bound detail
composition shows. ``SelectionMode`` is imported from ``table_selection_model``
rather than redefined: cardinality (``none``/``single``/``multi``) is the same
UI concept for a tree's nodes as for a table's rows, so one ``Literal`` names
it for both selection models.

Immutable: the verbs (``with_selection`` / ``with_anchor`` / ``reconciled``)
return a *new* model rather than mutating in place, and the element reassigns
``self._selection`` to it — the same rollback discipline ``TableSelectionModel``
documents for ``Element.apply_patch``'s all-or-nothing shallow-``vars()``
snapshot.

Construction stores the state *raw* so ``validate()`` (the decode gate, DES-039)
can report a wire selection that violates the mode; the verbs normalize, since
they run after the decode gate on already-valid state.
"""

from __future__ import annotations

from itertools import chain
from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements.table_selection_model import SelectionMode

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from punt_lux.protocol.elements.tree_node import TreeNode

__all__ = ["SelectionMode", "TreeSelectionModel"]


class TreeSelectionModel:
    """Selection state + cardinality for the tree's (visible) node selection.

    ``none`` is a display-only tree; ``single`` keeps at most one node; ``multi``
    holds a set. The ``anchor`` is the last-interacted node, carried explicitly
    (never inferred from the unordered set's order); ``""`` when empty.
    """

    _mode: SelectionMode
    _selected: frozenset[str]
    _anchor: str

    def __new__(
        cls,
        *,
        mode: SelectionMode = "none",
        selected: frozenset[str] = frozenset(),
        anchor: str = "",
    ) -> Self:
        self = super().__new__(cls)
        self._mode = mode
        self._selected = selected
        self._anchor = anchor
        return self

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport."""
        return (object.__new__, (type(self),), self.__dict__.copy())

    def __setstate__(self, state: dict[str, object]) -> None:
        """Restore instance state after native deserialization."""
        for key, value in state.items():
            object.__setattr__(self, key, value)

    @property
    def mode(self) -> SelectionMode:
        """Return the selection mode (``none`` / ``single`` / ``multi``)."""
        return self._mode

    @property
    def is_selectable(self) -> bool:
        """Return whether nodes can be selected (any mode other than ``none``)."""
        return self._mode != "none"

    @property
    def selected_node_ids(self) -> frozenset[str]:
        """Return the currently-selected node ids (the visible selection)."""
        return self._selected

    @property
    def anchor(self) -> str:
        """Return the last-interacted node's id, or ``""`` if none is selected."""
        return self._anchor

    def changed_from(self, other: TreeSelectionModel) -> bool:
        """Return whether the visible selection or anchor differs from ``other``."""
        return self._selected != other._selected or self._anchor != other._anchor

    def notify_if_changed(
        self, before: TreeSelectionModel, notify: Callable[[str], None]
    ) -> None:
        """Call ``notify("selected_node_ids")`` iff the selection moved from ``before``.

        ``TreeElement._set_nodes`` calls this after reconciling, so the element
        issues no conditional notify of its own — Tell, Don't Ask (PY-OO-5): the
        model that owns both compared fields also owns the decision.
        """
        if self.changed_from(before):
            notify("selected_node_ids")

    @staticmethod
    def live_ids(nodes: Iterable[TreeNode]) -> frozenset[str]:
        """Return every id ``nodes`` (and their descendants) use — the live-id
        source ``TreeElement`` reconciles the selection against on every write.
        """
        return frozenset(chain.from_iterable(n.ids() for n in nodes))

    def resolved_props(self) -> dict[str, object]:
        """Return the selection's three wire keys for ``TreeElement.resolved_props``."""
        return {
            "selection_mode": self._mode,
            "selected_node_ids": sorted(self._selected),
            "anchor_node_id": self._anchor,
        }

    def with_selection(self, node_ids: frozenset[str]) -> Self:
        """Return a new model with ``node_ids`` selected, mode-normalized.

        ``none`` clears; ``single`` keeps one; the anchor reseats onto a selected
        node. A following ``with_anchor`` names the node the user last touched.
        """
        selected, anchor = self._normalized(self._mode, node_ids, self._anchor)
        return type(self)(mode=self._mode, selected=selected, anchor=anchor)

    def with_anchor(self, anchor: str) -> Self:
        """Return a new model whose anchor is ``anchor`` if it names a selected node."""
        seated = anchor if anchor in self._selected else self._reseat(self._selected)
        return type(self)(mode=self._mode, selected=self._selected, anchor=seated)

    def reconciled(self, live_ids: frozenset[str]) -> Self:
        """Return a new model dropping selected ids no longer present.

        Called when the element's nodes change. A *surviving* anchor is kept — the
        last-interacted node a detail tracks must not jump on an unrelated nodes
        change — matching ``_normalized`` / ``with_anchor``; only an anchor whose
        node was removed reseats onto a survivor or clears.
        """
        selected = self._selected & live_ids
        anchor = self._anchor if self._anchor in selected else self._reseat(selected)
        return type(self)(mode=self._mode, selected=selected, anchor=anchor)

    @classmethod
    def _normalized(
        cls, mode: SelectionMode, selected: frozenset[str], anchor: str
    ) -> tuple[frozenset[str], str]:
        """Return the mode-enforced (selected, anchor) pair."""
        if mode == "none":
            return frozenset(), ""
        if mode == "single" and len(selected) > 1:
            keep = anchor if anchor in selected else min(selected)
            selected = frozenset({keep})
        seated = anchor if anchor in selected else cls._reseat(selected)
        return selected, seated

    @staticmethod
    def _reseat(selected: frozenset[str]) -> str:
        """Return a stable anchor for ``selected`` — its least id, or ``""``."""
        return min(selected) if selected else ""
