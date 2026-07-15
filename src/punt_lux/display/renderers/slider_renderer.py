# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for SliderElement — a commit-on-idle numeric slider.

While idle the thumb is synced to the Hub-authoritative ``elem.value``; while
being dragged the local buffer wins and a Hub-driven value is deferred. Exactly
one ``ValueChanged`` fires when the drag releases (via
``is_item_deactivated_after_edit``), never per drag frame — so a Hub re-push
landing mid-drag cannot clobber the value under the thumb. The commit fire is
wrapped for remote dispatch so the interaction runs on the Hub, not locally.

The arbiter keeps the buffer/commit-echo slots in ``float``; the integer
variant converts to ``int`` only at the ``slider_int`` call and in the fired
payload (``float(int)`` is exact, so this never perturbs reconciliation).
"""

from __future__ import annotations

from typing import Self, final

from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.slider_selection import SliderArbiter
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.slider import SliderElement
from punt_lux.scene import WidgetState
from punt_lux.tracing import trace

__all__ = ["SliderRenderer"]


@final
class SliderRenderer:
    """Render a SliderElement under the commit-on-idle rule.

    Holds the per-scene ``WidgetState`` (re-threaded on a scene switch) and
    builds a fresh ``SliderArbiter`` per element per frame; the arbiter owns
    the buffer/commit-echo slots, so this class stays a thin ImGui seam.
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
        arbiter = SliderArbiter(self._widget_state, elem.id)
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
        """Draw the int or float variant, returning ImGui's ``(changed, value)``.

        ImGui clamps the returned thumb position into ``[min, max]``, so the
        value handed back is always in range.
        """
        if elem.integer:
            return imgui.slider_int(label, int(resolved), int(elem.min), int(elem.max))
        return imgui.slider_float(
            label, float(resolved), float(elem.min), float(elem.max), elem.format
        )
