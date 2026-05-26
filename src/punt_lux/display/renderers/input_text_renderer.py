# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for InputTextElement — single-line text input with optional hint."""

from __future__ import annotations

import time
from typing import Self

from imgui_bundle import imgui

from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.scene import WidgetState
from punt_lux.types import EmitEventFn

__all__ = ["InputTextRenderer"]


class InputTextRenderer:
    """Render an InputTextElement via imgui.input_text or input_text_with_hint."""

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

    def render(self, elem: InputTextElement) -> None:
        eid = elem.id
        label = elem.label
        current = self._widget_state.ensure(eid, elem.value)
        if elem.hint:
            changed, new_val = imgui.input_text_with_hint(
                f"{label}##{eid}", elem.hint, current
            )
        else:
            changed, new_val = imgui.input_text(f"{label}##{eid}", current)
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
