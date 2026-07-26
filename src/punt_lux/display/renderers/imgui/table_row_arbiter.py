"""The table's row-selection bridge — hold the user's picks across the re-push.

The Display seeds its ImGui selection storage from the Hub-authoritative
``selected_row_ids`` each frame. Between a user gesture and the Hub's confirming
re-push that authoritative value stays *pre-gesture*, so a naive renderer both
flickers the just-clicked row off and — worse — drops the first pick when a
second gesture reseeds from the stale set (ctrl-click A fires ``{A}``, then
ctrl-click B reseeds from ``{}`` and fires ``{B}``, silently losing A).

The arbiter is the table's analogue of ``TabSelectionArbiter``: two per-scene
``WidgetState`` slots keep the fire decision testable without a live frame. The
*pending* slot holds the fired set optimistically through the gesture-to-re-push
window, so the display seeds from it and a second gesture accumulates. The
*honoured* slot records the authoritative set observed last frame; when the Hub
value moves off it — its own confirming re-push, or an unrelated push — the
pending is dropped and the fresh authoritative value wins. A re-added element
clears both slots (``WidgetState.discard_for``).
"""

from __future__ import annotations

from typing import Self, cast, final

from punt_lux.scene.widget_state import WidgetState

__all__ = ["TableSelectionArbiter"]


@final
class TableSelectionArbiter:
    """Bridge a table's row selection across the gesture-to-re-push window."""

    _state: WidgetState
    _pending_key: str
    _honoured_key: str
    __slots__ = ("_honoured_key", "_pending_key", "_state")

    def __new__(cls, state: WidgetState, element_id: str) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._pending_key = f"{element_id}{WidgetState.ROW_SELECTION_PENDING_SUFFIX}"
        self._honoured_key = f"{element_id}{WidgetState.ROW_SELECTION_HONOURED_SUFFIX}"
        return self

    def effective_selection(self, authoritative: frozenset[str]) -> frozenset[str]:
        """Return the set to seed the storage from this frame.

        While a gesture is outstanding, the pending set is held so the display
        keeps the user's accumulated picks. The Hub confirms a multi-pick
        incrementally — pending ``{A, B}`` may draw a re-push of ``{A}`` before
        one of ``{A, B}`` — and each such subset is *convergence*, not an
        override, so the pending is held until the Hub value reaches it exactly.
        The pending is dropped only when:

        - the Hub reaches ``pending`` exactly (fully confirmed), or
        - a genuinely foreign value arrives — one carrying an id never in
          ``pending`` (``authoritative`` is not a subset of ``pending``), or one
          that regressed below an id the Hub already confirmed (the last
          ``honoured`` set is not a subset of ``authoritative``).
        """
        pending = self._pending
        if pending is None:
            return authoritative
        if authoritative == pending:
            self._state.discard(self._pending_key)
            return authoritative
        if authoritative <= pending and self._honoured <= authoritative:
            return pending  # a converging subset re-push — keep the user's picks
        self._state.discard(self._pending_key)
        return authoritative

    def note_pending(self, fired: frozenset[str]) -> None:
        """Record the just-fired set so later frames hold it across the window."""
        self._state.set(self._pending_key, fired)

    def record_honoured(self, authoritative: frozenset[str]) -> None:
        """Record the authoritative set seen this frame (the end-of-frame write)."""
        self._state.set(self._honoured_key, authoritative)

    @property
    def _pending(self) -> frozenset[str] | None:
        # PY-TS-14 OK: ``None`` is the internal "no gesture outstanding" signal,
        # never returned to a caller — ``effective_selection`` maps it to the
        # authoritative value.
        value = self._state.get(self._pending_key)
        if isinstance(value, frozenset):
            return cast("frozenset[str]", value)
        return None

    @property
    def _honoured(self) -> frozenset[str]:
        """Return the authoritative set recorded last frame, ``frozenset()`` if none."""
        value = self._state.get(self._honoured_key)
        if isinstance(value, frozenset):
            return cast("frozenset[str]", value)
        return frozenset()
