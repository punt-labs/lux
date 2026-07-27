"""The autofocus arm/consume decision for a composed table's search input.

Keyboard focus should land in the search input when the composed table view first
arrives, and return there after the user types and hits Enter (the commit
otherwise drops focus). The fragile part — *when* to steal focus — is this pure
decision over two per-scene ``WidgetState`` slots, kept out of the ImGui seam so
it is testable without a live frame.

The slots are durable across a re-push: the poller replaces a composed scene
every few seconds, and focus must not be re-stolen on every resend — only on the
scene's true first arrival (``seen``) and after the input's own enter-commit
(``refocus``).
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.scene.widget_state import WidgetState

__all__ = ["SearchFocusArbiter"]


@final
class SearchFocusArbiter:
    """Decide when an autofocus input arms keyboard focus, from its scene slots."""

    _state: WidgetState
    _seen_key: str
    _refocus_key: str
    __slots__ = ("_refocus_key", "_seen_key", "_state")

    def __new__(cls, state: WidgetState, element_id: str) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._seen_key = f"{element_id}{WidgetState.FOCUS_SEEN_SUFFIX}"
        self._refocus_key = f"{element_id}{WidgetState.FOCUS_REFOCUS_SUFFIX}"
        return self

    def should_focus(self) -> bool:
        """Return whether to arm keyboard focus on this input this frame.

        True on the scene's first frame (focus has not been taken yet) and when a
        refocus is armed by a prior enter-commit; False otherwise, so focus is
        neither re-stolen on every resend nor yanked back on an unrelated blur.
        """
        return not self._seen or self._refocus_armed

    def record_focused(self) -> None:
        """Mark focus taken this frame: the scene is focused; disarm any refocus."""
        self._state.set(self._seen_key, value=True)
        self._state.discard(self._refocus_key)

    def arm_refocus(self) -> None:
        """Arm a refocus for the next frame — the input just enter-committed."""
        self._state.set(self._refocus_key, value=True)

    @property
    def _seen(self) -> bool:
        return bool(self._state.get(self._seen_key, False))

    @property
    def _refocus_armed(self) -> bool:
        return bool(self._state.get(self._refocus_key, False))
