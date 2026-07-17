# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Render a ``ModalElement`` — a popup that blocks background interaction.

Owns the modal open/dismiss latch and the child-recursion into the popup
body. Split out of ``ElementRenderer`` so the general element dispatch and
the modal subsystem each stay one responsibility (PY-IC-6). The latch lives
in the injected ``WidgetState`` keyed by element id, so the renderer holds no
frame-spanning state of its own; children recurse through the injected
``render_child`` callback, never a dispatch table.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Self, final

from imgui_bundle import imgui

from punt_lux.protocol import RemoteEventHandlerInvocation

if TYPE_CHECKING:
    from punt_lux.protocol import Element
    from punt_lux.protocol.elements.layout import ModalElement
    from punt_lux.scene import WidgetState
    from punt_lux.types import EmitEventFn

__all__ = ["ModalRenderer"]

# Recurse a child element back through the owning ElementRenderer's dispatch.
type RenderChildFn = Callable[[Element], None]

_MODAL_OPEN = 1
_MODAL_CLOSED = 0


@final
class ModalRenderer:
    """Paint a modal popup, latching its open/dismiss state in WidgetState."""

    _widget_state: WidgetState
    _emit_event: EmitEventFn
    _render_child: RenderChildFn

    def __new__(
        cls,
        widget_state: WidgetState,
        emit_event: EmitEventFn,
        render_child: RenderChildFn,
    ) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
        self._emit_event = emit_event
        self._render_child = render_child
        return self

    @property
    def widget_state(self) -> WidgetState:
        return self._widget_state

    @widget_state.setter
    def widget_state(self, value: WidgetState) -> None:
        self._widget_state = value

    def render(self, elem: ModalElement) -> None:
        """Paint the modal, driving its open/dismiss latch and child body."""
        eid = elem.id
        title = elem.title or elem.id
        popup_id = f"{title}##{eid}"
        open_key = f"{eid}__open"
        dismiss_key = f"{eid}__dismissed"

        was_open = self._widget_state.ensure(open_key, _MODAL_CLOSED) == _MODAL_OPEN
        dismissed = self._widget_state.ensure(dismiss_key, _MODAL_CLOSED) == _MODAL_OPEN

        # When the agent sets open=False, clear the dismissed latch
        # so the modal can be re-opened later.
        if not elem.open:
            if was_open or dismissed:
                self._widget_state.set(open_key, _MODAL_CLOSED)
                self._widget_state.set(dismiss_key, _MODAL_CLOSED)
            return

        # Don't re-open if user already dismissed and agent hasn't acked yet.
        if elem.open and not was_open and not dismissed:
            imgui.open_popup(popup_id)
            self._widget_state.set(open_key, _MODAL_OPEN)
            was_open = True

        closable = True
        visible, _p_open = imgui.begin_popup_modal(popup_id, closable)

        if visible:
            for child in elem.children:
                self._render_child(child)
            imgui.end_popup()

        if was_open and not visible:
            self._widget_state.set(open_key, _MODAL_CLOSED)
            self._widget_state.set(dismiss_key, _MODAL_OPEN)
            self._emit_event(
                RemoteEventHandlerInvocation(
                    element_id=eid,
                    action="closed",
                    ts=time.time(),
                    value=None,
                )
            )
