# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for ButtonElement — standard, arrow, and small button variants."""

from __future__ import annotations

import logging
from typing import Self

from imgui_bundle import imgui

from punt_lux.display.renderers._arrow import ArrowDirections
from punt_lux.domain.display_interaction import DisplayInteraction
from punt_lux.protocol.elements.button import ButtonElement

__all__ = ["ButtonRenderer"]

_log = logging.getLogger(__name__)


class ButtonRenderer:
    """Render a ButtonElement, handling arrow / small / disabled variants.

    On click, calls ``elem.fire(DisplayInteraction(...))`` which
    triggers the ``remote_dispatch`` handler installed by the
    display-side factory. The handler sends an ``RemoteEventHandlerInvocation``
    to the Hub over the socket. The renderer no longer constructs
    ``RemoteEventHandlerInvocation`` directly — distribution is the handler's
    concern (D21).
    """

    _arrows: ArrowDirections

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._arrows = ArrowDirections()
        return self

    def render(self, elem: ButtonElement) -> None:
        if elem.disabled:
            imgui.begin_disabled()
        clicked = self._click_button(elem)
        if clicked:
            _log.debug("button fire element_id=%s", elem.id)
            elem.fire(DisplayInteraction(element_id=elem.id))
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
