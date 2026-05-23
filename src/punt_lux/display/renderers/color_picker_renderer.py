# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for ColorPickerElement — RGB / RGBA edit and picker modes."""

from __future__ import annotations

import time
from typing import Self

from imgui_bundle import ImVec4, imgui

from punt_lux.display.renderers._color import parse_rgba
from punt_lux.protocol.elements.color_picker import ColorPickerElement
from punt_lux.protocol.messages.interaction import InteractionMessage
from punt_lux.scene import WidgetState
from punt_lux.types import EmitEventFn

__all__ = ["ColorPickerRenderer"]


class ColorPickerRenderer:
    """Render a ColorPickerElement, choosing edit / picker and RGB / RGBA variants."""

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

    def render(self, elem: ColorPickerElement) -> None:
        eid = elem.id
        r, g, b, a = parse_rgba(elem.value)
        initial = ImVec4(r / 255.0, g / 255.0, b / 255.0, a / 255.0)
        current = self._widget_state.ensure(eid, initial)
        changed, new_color = self._draw(elem, current)
        if changed:
            self._widget_state.set(eid, new_color)
            hex_val = self._encode(new_color, alpha=elem.alpha)
            self._emit_event(
                InteractionMessage(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value=hex_val,
                )
            )

    @staticmethod
    def _draw(elem: ColorPickerElement, current: ImVec4) -> tuple[bool, ImVec4]:
        label = elem.label
        eid = elem.id
        if elem.picker:
            if elem.alpha:
                return imgui.color_picker4(f"{label}##{eid}", current)
            return imgui.color_picker3(f"{label}##{eid}", current)
        if elem.alpha:
            return imgui.color_edit4(f"{label}##{eid}", current)
        return imgui.color_edit3(f"{label}##{eid}", current)

    @staticmethod
    def _encode(color: ImVec4, *, alpha: bool) -> str:
        r = int(max(0.0, min(1.0, color[0])) * 255)
        g = int(max(0.0, min(1.0, color[1])) * 255)
        b = int(max(0.0, min(1.0, color[2])) * 255)
        if alpha:
            a = int(max(0.0, min(1.0, color[3])) * 255)
            return f"#{r:02X}{g:02X}{b:02X}{a:02X}"
        return f"#{r:02X}{g:02X}{b:02X}"
