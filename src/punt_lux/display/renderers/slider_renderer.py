# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for SliderElement — int and float slider variants."""

from __future__ import annotations

import time
from typing import Self

from imgui_bundle import imgui

from punt_lux.protocol.elements.slider import SliderElement
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.scene import WidgetState
from punt_lux.types import EmitEventFn

__all__ = ["SliderRenderer"]


class SliderRenderer:
    """Render a SliderElement, dispatching to ``slider_int`` or ``slider_float``."""

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

    def render(self, elem: SliderElement) -> None:
        eid = elem.id
        label = elem.label
        current = self._widget_state.ensure(eid, elem.value)
        new_val: int | float
        if elem.integer:
            changed, new_val = imgui.slider_int(
                f"{label}##{eid}",
                int(current),
                int(elem.min),
                int(elem.max),
            )
        else:
            changed, new_val = imgui.slider_float(
                f"{label}##{eid}",
                float(current),
                float(elem.min),
                float(elem.max),
                elem.format,
            )
        if changed:
            self._widget_state.set(eid, new_val)
            self._emit_event(
                RemoteEventHandlerInvocation(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value=new_val,
                )
            )
