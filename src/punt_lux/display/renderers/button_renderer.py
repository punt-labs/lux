# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for ButtonElement — standard, arrow, and small button variants."""

from __future__ import annotations

import logging
import time
from typing import Self

from imgui_bundle import imgui

from punt_lux.display.renderers._arrow import ArrowDirections
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.messages.interaction import InteractionMessage
from punt_lux.types import EmitEventFn

__all__ = ["ButtonRenderer"]

_log = logging.getLogger(__name__)


class ButtonRenderer:
    """Render a ButtonElement, handling arrow / small / disabled variants."""

    _emit_event: EmitEventFn
    _arrows: ArrowDirections

    def __new__(cls, emit_event: EmitEventFn) -> Self:
        self = super().__new__(cls)
        self._emit_event = emit_event
        self._arrows = ArrowDirections()
        return self

    def render(self, elem: ButtonElement) -> None:
        action = elem.action or elem.id
        if elem.disabled:
            imgui.begin_disabled()
        clicked = self._click_button(elem)
        if clicked:
            self._emit_event(
                InteractionMessage(
                    element_id=elem.id,
                    action=action,
                    ts=time.time(),
                    value=True,
                )
            )
        if elem.disabled:
            imgui.end_disabled()

    def _click_button(self, elem: ButtonElement) -> bool:
        label = elem.label
        eid = elem.id
        if elem.arrow:
            direction = self._arrows.resolve(elem.arrow)
            if direction is None:
                _log.warning("Unknown arrow direction %r for %s", elem.arrow, eid)
                return imgui.button(f"{label}##{eid}")
            return imgui.arrow_button(f"##{eid}", direction)
        if elem.small:
            return imgui.small_button(f"{label}##{eid}")
        return imgui.button(f"{label}##{eid}")
