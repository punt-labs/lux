"""Synthetic interactions for a display running in test mode.

A display started with ``test_auto_click`` answers each scene it receives as
though the user had immediately operated every control in it: a button is
clicked, a slider moved, a checkbox flipped. An end-to-end test can then
exercise the whole click path — display to Hub to handler — with no window and
no hands. Nothing here runs in a display serving a user.

The synthetic value for each kind is the one a real interaction would carry, so
the Hub cannot tell the difference: a checkbox reports the value it would have
after the click, a slider its current value, a combo its selected index.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.protocol import (
    ButtonElement,
    CheckboxElement,
    ColorPickerElement,
    ComboElement,
    InputTextElement,
    RadioElement,
    RemoteEventHandlerInvocation,
    SelectableElement,
    SliderElement,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.protocol import SceneMessage
    from punt_lux.protocol.elements import Element

__all__ = ["AutoClicker"]


@final
class AutoClicker:
    """Emit one synthetic interaction per interactive element of a received scene."""

    _emit: Callable[[RemoteEventHandlerInvocation], None]
    __slots__ = ("_emit",)

    def __new__(cls, emit: Callable[[RemoteEventHandlerInvocation], None]) -> Self:
        self = super().__new__(cls)
        self._emit = emit
        return self

    def click_all(self, msg: SceneMessage) -> None:
        """Emit a synthetic interaction for every element of ``msg`` that has one."""
        for elem in msg.elements:
            invocation = self._synthetic(elem)
            if invocation is not None:
                self._emit(invocation)

    def _synthetic(self, elem: Element) -> RemoteEventHandlerInvocation | None:
        """Return the interaction ``elem`` would report, or ``None`` if it has none.

        ``None`` is the documented "this kind is not interactive, or is
        disabled" answer, not a failure — most elements of a scene are inert.
        """
        if isinstance(elem, ButtonElement):
            if elem.disabled:
                return None
            action = elem.action or elem.id
            return self._invocation(elem.id, action, "button_clicked", value=True)
        changed = self._changed(elem)
        if changed is None:
            return None
        action, value = changed
        return self._invocation(elem.id, action, "value_changed", value=value)

    def _changed(self, elem: Element) -> tuple[str, object] | None:
        """Return the action and value a change to ``elem`` reports, or ``None``.

        The combo, radio, and selectable kinds report a scalar — the selected
        index, or the selection state the click leaves behind — matching what
        their renderers fire; ``value_changed`` accepts nothing else.
        """
        if isinstance(elem, SliderElement):
            return "changed", int(elem.value) if elem.integer else elem.value
        if isinstance(elem, CheckboxElement):
            return elem.action, not elem.value
        if isinstance(elem, ComboElement):
            return "changed", elem.selected
        if isinstance(elem, InputTextElement):
            return "changed", elem.value
        if isinstance(elem, RadioElement):
            return "changed", elem.selected
        if isinstance(elem, ColorPickerElement):
            return "changed", elem.value
        if isinstance(elem, SelectableElement):
            return "clicked", not elem.selected
        return None

    @staticmethod
    def _invocation(
        element_id: str, action: str, event_kind: str, *, value: object
    ) -> RemoteEventHandlerInvocation:
        """Build one synthetic invocation, stamped with the time it was made."""
        return RemoteEventHandlerInvocation(
            element_id=element_id,
            action=action,
            event_kind=event_kind,
            ts=time.time(),
            value=value,
        )
