# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for ComboElement — dropdown combo box."""

from __future__ import annotations

import logging
import time
from typing import Self

from imgui_bundle import imgui

from punt_lux.protocol.elements.combo import ComboElement
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.scene import WidgetState
from punt_lux.types import EmitEventFn

__all__ = ["ComboRenderer"]

_log = logging.getLogger(__name__)


class ComboRenderer:
    """Render a ComboElement via imgui.combo."""

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

    def render(self, elem: ComboElement) -> None:
        eid = elem.id
        label = elem.label
        items = elem.items
        if not items:
            imgui.text(f"{label}: (empty)")
            return
        initial = max(0, min(elem.selected, len(items) - 1))
        current = self._widget_state.ensure(eid, initial)
        if current < 0 or current >= len(items):
            _log.warning(
                "combo %s widget_state index %d out of range [0,%d); resetting to 0",
                eid,
                current,
                len(items),
            )
            current = 0
            self._widget_state.set(eid, current)
        changed, new_val = imgui.combo(f"{label}##{eid}", current, items)
        if changed:
            self._widget_state.set(eid, new_val)
            item_text = items[new_val] if 0 <= new_val < len(items) else ""
            self._emit_event(
                RemoteEventHandlerInvocation(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value={"index": new_val, "item": item_text},
                )
            )
