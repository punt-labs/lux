# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for InputNumberElement — numeric input with step + clamping bounds."""

from __future__ import annotations

import time
from typing import Self

from imgui_bundle import imgui

from punt_lux.protocol.elements.input_number import InputNumberElement
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.scene import WidgetState
from punt_lux.types import EmitEventFn

__all__ = ["InputNumberRenderer"]


class InputNumberRenderer:
    """Render an InputNumberElement with optional integer mode and bounds."""

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

    def render(self, elem: InputNumberElement) -> None:
        eid = elem.id
        initial: int | float = self._clamped_initial(elem)
        current = self._widget_state.ensure(eid, initial)
        result, changed = self._draw_input(elem, current)
        result, changed = self._enforce_bounds(elem, result, changed=changed)
        if changed:
            self._widget_state.set(eid, result)
            self._emit_event(
                RemoteEventHandlerInvocation(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value=result,
                )
            )

    @staticmethod
    def _clamped_initial(elem: InputNumberElement) -> int | float:
        initial: int | float = elem.value
        if elem.min is not None and initial < elem.min:
            initial = int(elem.min) if elem.integer else elem.min
        if elem.max is not None and initial > elem.max:
            initial = int(elem.max) if elem.integer else elem.max
        return initial

    @staticmethod
    def _draw_input(
        elem: InputNumberElement, current: int | float
    ) -> tuple[int | float, bool]:
        label = elem.label
        eid = elem.id
        if elem.integer:
            step = int(elem.step) if elem.step is not None else 0
            changed, value_int = imgui.input_int(
                f"{label}##{eid}", int(current), step, step * 10
            )
            return value_int, changed
        step_f = elem.step if elem.step is not None else 0.0
        changed, value_f = imgui.input_float(
            f"{label}##{eid}", float(current), step_f, step_f * 10.0, elem.format
        )
        return value_f, changed

    @staticmethod
    def _enforce_bounds(
        elem: InputNumberElement,
        result: int | float,
        *,
        changed: bool,
    ) -> tuple[int | float, bool]:
        if elem.min is not None and result < elem.min:
            result = int(elem.min) if elem.integer else elem.min
            changed = True
        if elem.max is not None and result > elem.max:
            result = int(elem.max) if elem.integer else elem.max
            changed = True
        return result, changed
