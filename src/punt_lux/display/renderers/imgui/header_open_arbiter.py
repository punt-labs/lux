"""The collapsing header's open-state arbiter — hold the toggle across the re-push.

An ImGui collapsing header keeps its own stored open state, and
``set_next_item_open`` overwrites it. Writing the Hub-authoritative flag there on
every frame looks right and produces a visible double-step: the click frame flips
ImGui's memory and the section opens, the next frame writes the Hub value back —
the Hub has not heard about the click yet, so it still says closed — and the
section snaps shut, and only when the confirming re-push lands does it open
again. One click, three rendered states.

The arbiter holds the toggle across that window in one per-scene ``WidgetState``
slot: the open state a ``HeaderToggled`` has been fired for and the Hub has not
yet ratified. ``effective_open`` returns that value while it is outstanding and
the Hub's otherwise, so the frame writes what the user asked for and the click's
transition stands. The slot lasts exactly until the Hub next speaks — it takes
one of the per-render-session suffixes, which a re-push clears
(``reset_session_slots``) and a removal clears (``discard_for``) — so a toggle
the Hub *rejects* pulls the display back to the Hub's value rather than
stranding the user's optimistic view.

The same value decides the fire. The renderer fires when what ImGui reports
differs from what ``effective_open`` asked for, so once the click's value is
pending the following frames ask for it, are given it, and stay silent: the
window fires exactly once, and no ``fire -> Hub -> re-push -> fire`` loop can
form. Comparing against the raw Hub value instead would fire on every frame of
the window.

This is the header's analogue of ``TabSelectionArbiter`` and
``TableSelectionArbiter``, and the smallest of the three: a tab bar compares
against the Hub value to force-select and against it again to fire, so it needs
a honoured slot beside its pending one, whereas a header compares against the
effective value in both places and one slot serves. The discipline is
model-checked in ``docs/header_toggle_reconciliation.tex``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.scene.widget_state import WidgetState

if TYPE_CHECKING:
    from punt_lux.protocol.elements.collapsing_header import CollapsingHeaderElement

__all__ = ["HeaderOpenArbiter"]


@final
class HeaderOpenArbiter:
    """Arbitrate a collapsing header's open state across the click-to-re-push window."""

    _state: WidgetState
    _pending_key: str
    __slots__ = ("_pending_key", "_state")

    def __new__(cls, state: WidgetState, element_id: str) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._pending_key = f"{element_id}{WidgetState.HEADER_OPEN_PENDING_SUFFIX}"
        return self

    @classmethod
    def for_element(cls, state: WidgetState, elem: CollapsingHeaderElement) -> Self:
        """Return the arbiter for one header — the renderer's per-frame entry."""
        return cls(state, elem.id)

    def effective_open(self, *, authoritative: bool) -> bool:
        """Return the open state this frame must render.

        The outstanding toggle while one is pending, the Hub's value otherwise.
        The fall-through is the ``default`` of the read rather than a branch on
        absence: nothing pending — and a slot not holding a flag is nothing
        pending — leaves the Hub's value, which is what the display owes.
        """
        return self._state.get_bool(self._pending_key, default=authoritative)

    def note_pending(self, *, fired: bool) -> None:
        """Record the open state just fired, so the window holds it and stays silent."""
        self._state.set(self._pending_key, fired)
