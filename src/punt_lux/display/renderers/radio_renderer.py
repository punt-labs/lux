# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for RadioElement — a horizontal set of radio buttons."""

from __future__ import annotations

import logging
import time
from typing import Self

from imgui_bundle import imgui

from punt_lux.protocol.elements.radio import RadioElement
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.scene import WidgetState
from punt_lux.types import EmitEventFn

__all__ = ["RadioRenderer"]

_log = logging.getLogger(__name__)


class RadioRenderer:
    """Render a RadioElement as a horizontal list of radio buttons."""

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

    def render(self, elem: RadioElement) -> None:
        eid = elem.id
        label = elem.label
        items = elem.items
        current: int = self._widget_state.ensure(eid, elem.selected)
        if items and (current < 0 or current >= len(items)):
            _log.warning(
                "radio %s widget_state index %d out of range [0,%d); resetting to 0",
                eid,
                current,
                len(items),
            )
            current = 0
            self._widget_state.set(eid, 0)
        if label:
            imgui.text(label)
        for i, item in enumerate(items):
            if imgui.radio_button(f"{item}##{eid}_{i}", current == i) and current != i:
                self._widget_state.set(eid, i)
                self._emit_event(
                    RemoteEventHandlerInvocation(
                        element_id=eid,
                        action="changed",
                        ts=time.time(),
                        value={"index": i, "item": item},
                    )
                )
                current = i
            if i < len(items) - 1:
                imgui.same_line()
