"""The tab-bar fire/honour arbiter — force-select and fire from two slots.

A ``tab_bar`` carries one Hub-authoritative selection, the *active* tab, and is
rendered every frame by an ImGui tab bar that keeps its own idea of which tab is
selected. The arbiter reconciles the two from two per-scene ``WidgetState``
slots, so the fire decision — the fragile part — is testable without a live
ImGui frame.

The *honoured* slot (default ``_UNHONOURED``) records the active tab the last
frame force-selected, so a fresh Hub value is honoured without firing: ImGui's
tab-0 default never clobbers a declared active tab. The *pending* slot (default
``_NO_PENDING``) records the tab a ``TabChanged`` is already outstanding for; it
holds through the click-to-re-push window, where ImGui still reports the clicked
tab before the Hub catches up, so the window fires exactly once. A re-push or
removal clears both slots (see ``WidgetState``).
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.scene.widget_state import WidgetState

__all__ = ["TabSelectionArbiter"]

_UNHONOURED = "\x00unhonoured"  # no Hub active tab honoured yet this scene
_NO_PENDING = "\x00nopending"  # no outstanding TabChanged this render session


@final
class TabSelectionArbiter:
    """Arbitrate a tab bar's force-select and fire from its two WidgetState slots."""

    _state: WidgetState
    _honoured_key: str
    _pending_key: str

    def __new__(cls, state: WidgetState, element_id: str) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._honoured_key = f"{element_id}{WidgetState.HONOURED_SUFFIX}"
        self._pending_key = f"{element_id}{WidgetState.PENDING_SUFFIX}"
        return self

    def should_force_select(self, tab_id: str, active: str) -> bool:
        """Return whether to force-select this tab — the Hub value changed this frame.

        Before anything is honoured the slot reads ``_UNHONOURED``, so a non-first
        declared active tab is force-selected the first frame, over ImGui's tab-0
        default.
        """
        return active != self._honoured and tab_id == active

    def should_fire(self, *, selected: bool, tab_id: str, active: str) -> bool:
        """Return whether this frame fires, recording the pending tab if it does.

        A tab already outstanding (in the pending slot) never re-fires: through
        the click-to-re-push window every later frame sees it pending and stays
        silent, so the window fires exactly once.
        """
        if tab_id == self._state.get(self._pending_key, _NO_PENDING):
            return False
        if not self._is_user_switch(selected=selected, tab_id=tab_id, active=active):
            return False
        self._state.set(self._pending_key, tab_id)
        return True

    def record_honoured(self, active: str) -> None:
        """Record the active tab this frame honoured — the once-per-frame end write."""
        self._state.set(self._honoured_key, active)

    @property
    def _honoured(self) -> str:
        """Return the active tab the last frame force-selected, or ``_UNHONOURED``."""
        return str(self._state.get(self._honoured_key, _UNHONOURED))

    def _is_user_switch(self, *, selected: bool, tab_id: str, active: str) -> bool:
        """Return whether this reported selection is a genuine user tab switch.

        A tab not reported selected, or already active, is no switch. A frame that
        honoured a fresh Hub value (``active`` differs from the honoured value,
        ``_UNHONOURED`` before the first honour) is the echo — it does not fire.
        """
        if not selected or tab_id == active:
            return False
        return active == self._honoured
