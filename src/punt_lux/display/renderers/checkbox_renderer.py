# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for CheckboxElement — emits an ImGui checkbox."""

from __future__ import annotations

from typing import Self

from imgui_bundle import imgui

from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.scene import WidgetState

__all__ = ["CheckboxRenderer"]


class CheckboxRenderer:
    """Render a CheckboxElement via imgui.checkbox.

    On toggle, fires ``ValueChanged`` through the element's handler
    registry. On the display side, handlers are wrapped by
    ``remote_dispatch`` which sends a ``RemoteEventHandlerInvocation``
    to the Hub over the socket instead of executing the real handler
    body.
    """

    _widget_state: WidgetState

    def __new__(cls, widget_state: WidgetState) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
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
            elem.fire(
                ValueChanged(
                    scene_id=SceneId("__display__"),
                    element_id=ElementId(eid),
                    owner_id=ClientId("__display__"),
                    value=new_val,
                )
            )
