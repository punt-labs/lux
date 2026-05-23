# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for CheckboxElement — emits an ImGui checkbox."""

from __future__ import annotations

import time
from typing import Self

from imgui_bundle import imgui

from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.messages.interaction import InteractionMessage
from punt_lux.scene import WidgetState
from punt_lux.types import EmitEventFn

__all__ = ["CheckboxRenderer"]


class CheckboxRenderer:
    """Render a CheckboxElement via imgui.checkbox."""

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

    def render(self, elem: CheckboxElement) -> None:
        eid = elem.id
        label = elem.label
        current = self._widget_state.ensure(eid, elem.value)
        changed, new_val = imgui.checkbox(f"{label}##{eid}", current)
        if changed:
            self._widget_state.set(eid, new_val)
            self._emit_event(
                InteractionMessage(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value=new_val,
                )
            )
