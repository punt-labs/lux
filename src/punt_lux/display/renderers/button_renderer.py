# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for ButtonElement — standard, arrow, and small button variants."""

from __future__ import annotations

import logging
from typing import Self

from imgui_bundle import imgui

from punt_lux.display.renderers._arrow import ArrowDirections
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.tracing import trace

__all__ = ["ButtonRenderer"]

_log = logging.getLogger(__name__)


class ButtonRenderer:
    """Render a ButtonElement, handling arrow / small / disabled variants.

    On click, fires ``ButtonClicked`` through the element's handler
    registry. On the display side, handlers are wrapped for
    ``remote_dispatch`` by ``DisplayServer._wrap_abc_elements`` (calling
    ``elem.wrap_handlers_for_remote``), which sends a
    ``RemoteEventHandlerInvocation`` to the Hub over the socket instead of
    executing the real handler body. On the Hub side they run unwrapped.
    """

    _arrows: ArrowDirections

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._arrows = ArrowDirections()
        return self

    @trace
    def render(self, elem: ButtonElement) -> None:
        if elem.disabled:
            imgui.begin_disabled()
        clicked = self._click_button(elem)
        if clicked:
            _log.debug("button fire element_id=%s", elem.id)
            elem.fire(
                ButtonClicked(
                    scene_id=SceneId("__display__"),
                    element_id=ElementId(elem.id),
                    owner_id=ClientId("__display__"),
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
