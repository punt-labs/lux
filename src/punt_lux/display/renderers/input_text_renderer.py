# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for InputTextElement — a Hub-honouring single-line text input.

Paints ``imgui.input_text`` (or ``input_text_with_hint``) against a per-element
buffer the ``InputTextArbiter`` reconciles with the Hub-authoritative
``elem.value``: a Hub drive replaces the buffer, the user's in-progress text
survives an in-flight echo, and a genuine edit fires ``ValueChanged`` (wrapped
for D21 remote dispatch on the display side). No echo re-fires — ``imgui``
reports ``changed`` only on a real edit.
"""

from __future__ import annotations

from typing import Self

from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.input_text_selection import InputTextArbiter
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.scene import WidgetState
from punt_lux.tracing import trace

__all__ = ["InputTextRenderer"]


class InputTextRenderer:
    """Render an InputTextElement, honouring the Hub value without clobbering typing.

    The renderer holds the per-scene ``WidgetState`` (re-threaded on a scene
    switch) and builds a fresh ``InputTextArbiter`` per element per frame; the
    arbiter owns the buffer/honoured slots, so this class stays a thin ImGui
    seam. On a genuine edit it fires ``ValueChanged`` through the element's
    handler registry — wrapped for remote dispatch by
    ``DisplayServer._wrap_abc_elements`` — so the interaction routes to the Hub
    instead of running the real handler body locally.
    """

    _widget_state: WidgetState

    def __new__(cls, widget_state: WidgetState) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
        return self

    @property
    def widget_state(self) -> WidgetState:
        """Return the per-scene widget state the buffer/honour slots live in."""
        return self._widget_state

    @widget_state.setter
    def widget_state(self, value: WidgetState) -> None:
        """Re-thread the renderer to the scene being rendered."""
        self._widget_state = value

    @trace
    def render(self, elem: InputTextElement) -> None:
        arbiter = InputTextArbiter(self._widget_state, elem.id)
        current = arbiter.buffer(elem.value)
        label = f"{elem.label}##{elem.id}"
        if elem.hint:
            changed, new_val = imgui.input_text_with_hint(label, elem.hint, current)
        else:
            changed, new_val = imgui.input_text(label, current)
        if changed:
            arbiter.record_edit(new_val)
            elem.fire(
                ValueChanged(
                    scene_id=SceneId("__display__"),
                    element_id=ElementId(elem.id),
                    owner_id=ClientId("__display__"),
                    value=new_val,
                )
            )
