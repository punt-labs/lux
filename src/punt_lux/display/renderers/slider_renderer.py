# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for SliderElement — a commit-on-idle numeric slider.

Idle, the thumb tracks ``elem.value``; while dragged the local buffer wins and a
Hub value is deferred, so a re-push landing mid-drag cannot clobber the thumb.
Exactly one ``ValueChanged`` fires on release, wrapped for remote dispatch. The
arbiter buffers a ``float``; the integer variant converts to ``int`` only at
``slider_int`` and in the payload (``float(int)`` is exact).
"""

from __future__ import annotations

from typing import Self, final

from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.continuous_edit_accessors import (
    FloatValueAccessor,
)
from punt_lux.display.renderers.imgui.continuous_edit_selection import (
    ContinuousEditArbiter,
)
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.slider import SliderElement
from punt_lux.scene import WidgetState
from punt_lux.tracing import trace

__all__ = ["SliderRenderer"]

# The float accessor is stateless, so one shared instance serves every frame.
_ACCESSOR = FloatValueAccessor()


@final
class SliderRenderer:
    """Render a SliderElement under the commit-on-idle rule.

    Holds the per-scene ``WidgetState`` and builds a fresh
    ``ContinuousEditArbiter`` (with a ``FloatValueAccessor``) per frame; the
    arbiter owns the buffer/commit-echo slots, so this stays a thin ImGui seam.
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
    def render(self, elem: SliderElement) -> None:
        arbiter = ContinuousEditArbiter(self._widget_state, elem.id, _ACCESSOR)
        label = f"{elem.label}##{elem.id}"
        resolved = arbiter.resolve(elem.value)
        changed, new_val = self._draw(elem, label, resolved)
        if imgui.is_item_active():
            arbiter.observe(edited=changed, value=float(new_val))
        else:
            arbiter.release()
        if imgui.is_item_deactivated_after_edit():
            elem.fire(
                ValueChanged(
                    scene_id=SceneId("__display__"),
                    element_id=ElementId(elem.id),
                    owner_id=ClientId("__display__"),
                    value=new_val,
                )
            )
            arbiter.commit(float(new_val), elem.value)

    @staticmethod
    def _draw(
        elem: SliderElement, label: str, resolved: float
    ) -> tuple[bool, int | float]:
        """Draw the int/float variant; ImGui clamps ``(changed, value)`` into range."""
        if elem.integer:
            return imgui.slider_int(label, int(resolved), int(elem.min), int(elem.max))
        return imgui.slider_float(
            label, float(resolved), float(elem.min), float(elem.max), elem.format
        )
