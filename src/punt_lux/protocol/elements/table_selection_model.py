"""``TableSelectionModel`` — the basic grid's private, immutable selection state.

Owned by ``TableElement`` (composition, PY-IC-1); nothing outside the table
constructs it or calls its verbs. It holds the selection *mode*, the selected
``row_id`` *set*, and the *anchor* — the last-interacted row a bound detail
composition shows.

Immutable: the verbs (``with_selection`` / ``with_anchor`` / ``reconciled``)
return a *new* model rather than mutating in place, and the element reassigns
``self._selection`` to it. That keeps ``Element.apply_patch``'s all-or-nothing
rollback honest — the shallow ``vars()`` snapshot captures the old model object,
so a later setter's failure restores the whole selection, not a half-mutated one.

Construction stores the state *raw* so ``validate()`` (the decode gate, DES-039)
can report a wire selection that violates the mode; the verbs normalize, since
they run after the decode gate on already-valid state.
"""

from __future__ import annotations

from typing import Literal, Self

__all__ = ["SelectionMode", "TableSelectionModel"]

SelectionMode = Literal["none", "single", "multi"]


class TableSelectionModel:
    """Selection state + cardinality for the element's (visible) selection.

    ``none`` is a display-only grid; ``single`` keeps at most one row; ``multi``
    holds a set. The ``anchor`` is the last-interacted row, carried explicitly
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
        """Return whether rows can be selected (any mode other than ``none``)."""
        return self._mode != "none"

    @property
    def selected_row_ids(self) -> frozenset[str]:
        """Return the currently-selected row ids (the visible selection)."""
        return self._selected

    @property
    def anchor(self) -> str:
        """Return the last-interacted row's id, or ``""`` if none is selected."""
        return self._anchor

    def with_selection(self, row_ids: frozenset[str]) -> Self:
        """Return a new model with ``row_ids`` selected, mode-normalized.

        ``none`` clears; ``single`` keeps one; the anchor reseats onto a selected
        row. A following ``with_anchor`` names the row the user last touched.
        """
        selected, anchor = self._normalized(self._mode, row_ids, self._anchor)
        return type(self)(mode=self._mode, selected=selected, anchor=anchor)

    def with_anchor(self, anchor: str) -> Self:
        """Return a new model whose anchor is ``anchor`` if it names a selected row."""
        seated = anchor if anchor in self._selected else self._reseat(self._selected)
        return type(self)(mode=self._mode, selected=self._selected, anchor=seated)

    def reconciled(self, live_ids: frozenset[str]) -> Self:
        """Return a new model dropping selected ids no longer present.

        Called when the element's rows change. A *surviving* anchor is kept — the
        last-interacted row a detail tracks must not jump on an unrelated rows
        change (a filter reproject patches rows without an anchor) — matching
        ``_normalized`` / ``with_anchor``; only an anchor whose row was removed
        reseats onto a survivor or clears.
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
