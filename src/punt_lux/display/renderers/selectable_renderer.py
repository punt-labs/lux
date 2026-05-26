# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for SelectableElement — toggleable list item."""

from __future__ import annotations

import time
from typing import Self

from imgui_bundle import imgui

from punt_lux.protocol.elements.selectable import SelectableElement
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.scene import WidgetState
from punt_lux.types import EmitEventFn

__all__ = ["SelectableRenderer"]


class SelectableRenderer:
    """Render a SelectableElement via imgui.selectable."""

    _widget_state: WidgetState
    _emit_event: EmitEventFn

    def __new__(cls, widget_state: WidgetState, emit_event: EmitEventFn) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
        self._emit_event = emit_event
        return self

    @property
    def widget_state(self) -> WidgetState:
        return self._widget_state

    @widget_state.setter
    def widget_state(self, value: WidgetState) -> None:
        self._widget_state = value

    def render(self, elem: SelectableElement) -> None:
        eid = elem.id
        label = elem.label
        current: bool = self._widget_state.ensure(eid, elem.selected)
        clicked, new_val = imgui.selectable(f"{label}##{eid}", current)
        if clicked:
            self._widget_state.set(eid, new_val)
            self._emit_event(
                RemoteEventHandlerInvocation(
                    element_id=eid,
                    action="clicked",
                    ts=time.time(),
                    value=new_val,
                )
            )
