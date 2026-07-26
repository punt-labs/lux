"""``TableSelectionModel`` — the basic grid's private selection state.

Owned by ``TableElement`` (composition, PY-IC-1); mirrors ``ModalModel`` in that
nothing outside the table constructs it or calls its verbs. It holds the
selection *mode*, the selected ``row_id`` *set*, and the *anchor* — the
last-interacted row a bound detail composition shows.

Construction stores the state *raw* so ``validate()`` (the decode gate, DES-039)
can report a wire selection that violates the mode — ``single`` with two ids, an
anchor naming no selected row. The gesture / agent-drive verbs enforce the mode,
since they run after the decode gate on already-valid state.
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

    def set_selected_ids(self, row_ids: frozenset[str]) -> None:
        """Replace the selection from a gesture/drive; enforce the mode.

        ``none`` clears, ``single`` keeps one; the anchor reseats onto a selected
        row, and a following ``set_anchor`` names the last-touched one.
        """
        self._selected = row_ids
        self._enforce_mode()

    def set_anchor(self, anchor: str) -> None:
        """Set the anchor; keep it only if it names a selected row."""
        self._anchor = anchor
        self._reseat_anchor()

    def reconcile(self, live_ids: frozenset[str]) -> None:
        """Drop selected ids no longer present and reseat a departed anchor.

        Called when the element's rows change (a removed row leaves the selection).
        """
        self._selected = self._selected & live_ids
        self._reseat_anchor()

    def _enforce_mode(self) -> None:
        """Apply the per-mode cardinality after a gesture/drive selection."""
        if self._mode == "none":
            self._selected = frozenset()
            self._anchor = ""
            return
        if self._mode == "single" and len(self._selected) > 1:
            keep = (
                self._anchor if self._anchor in self._selected else min(self._selected)
            )
            self._selected = frozenset({keep})
        self._reseat_anchor()

    def _reseat_anchor(self) -> None:
        """Keep the anchor on a selected row, or ``""`` when none remain."""
        if self._anchor in self._selected:
            return
        self._anchor = min(self._selected) if self._selected else ""
