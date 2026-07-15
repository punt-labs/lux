# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for InputTextElement — a commit-on-idle single-line text input.

Idle, the buffer tracks ``elem.value``; while edited the local buffer wins and a
Hub value is deferred, so pipelined edits cannot clobber live typing. Exactly one
``ValueChanged`` fires on commit (blur or Enter), wrapped for remote dispatch.
"""

from __future__ import annotations

from typing import Self

from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.continuous_edit_accessors import StrValueAccessor
from punt_lux.display.renderers.imgui.continuous_edit_selection import (
    ContinuousEditArbiter,
)
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.scene import WidgetState
from punt_lux.tracing import trace

__all__ = ["InputTextRenderer"]

# The str accessor is stateless, so one shared instance serves every frame.
_ACCESSOR = StrValueAccessor()


class InputTextRenderer:
    """Render an InputTextElement under the commit-on-idle rule.

    Holds the per-scene ``WidgetState`` and builds a fresh
    ``ContinuousEditArbiter`` (with a ``StrValueAccessor``) per frame; the
    arbiter owns the buffer/editing slots, so this stays a thin ImGui seam.
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
        arbiter = ContinuousEditArbiter(self._widget_state, elem.id, _ACCESSOR)
        label = f"{elem.label}##{elem.id}"
        changed, text = imgui.input_text_with_hint(
            label, elem.hint, arbiter.resolve(elem.value)
        )
        if imgui.is_item_active():
            arbiter.observe(edited=changed, value=text)
        else:
            arbiter.release()
        if imgui.is_item_deactivated_after_edit():
            elem.fire(
                ValueChanged(
                    scene_id=SceneId("__display__"),
                    element_id=ElementId(elem.id),
                    owner_id=ClientId("__display__"),
                    value=text,
                )
            )
            arbiter.commit(text, elem.value)
