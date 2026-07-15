# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for ColorPickerElement — a commit-on-idle RGB(A) color picker.

Idle, the color tracks ``elem.value`` (a hex string parsed to a tuple); while a
sub-control is dragged the local buffer wins and a Hub value is deferred, so a
re-push landing mid-drag cannot clobber the color. Exactly one ``ValueChanged``
fires on a sub-control release, wrapped for remote dispatch. The arbiter buffers
RGBA tuples; the wire fire carries a hex string, and on release the *quantized*
(8-bit round-tripped) tuple is committed so it bit-equals the echo — no
full-precision→8-bit pop while the window is open.
"""

from __future__ import annotations

from typing import Self, final

from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.color_channel_strip import ColorChannelStrip
from punt_lux.display.renderers.imgui.continuous_edit_accessors import (
    ColorValueAccessor,
)
from punt_lux.display.renderers.imgui.continuous_edit_selection import (
    ContinuousEditArbiter,
)
from punt_lux.display.renderers.imgui.full_color_picker import FullColorPicker
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.color_picker import ColorPickerElement
from punt_lux.protocol.elements.rgba_color import Rgba, RgbaColor
from punt_lux.scene import WidgetState
from punt_lux.tracing import trace

__all__ = ["ColorPickerRenderer"]

# The accessor, channel strip, and full picker are stateless — one shared each.
_ACCESSOR = ColorValueAccessor()
_STRIP = ColorChannelStrip()
_PICKER = FullColorPicker()


@final
class ColorPickerRenderer:
    """Render a ColorPickerElement under the commit-on-idle rule.

    Holds the per-scene ``WidgetState`` and builds a fresh
    ``ContinuousEditArbiter`` (with a ``ColorValueAccessor``) per frame; the
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
    def render(self, elem: ColorPickerElement) -> None:
        arbiter = ContinuousEditArbiter(self._widget_state, elem.id, _ACCESSOR)
        hub_tuple = RgbaColor.from_hex(elem.value).as_tuple()
        resolved = arbiter.resolve(hub_tuple)
        changed, new_tuple = self._draw(elem, resolved)
        if imgui.is_item_active():
            arbiter.observe(edited=changed, value=new_tuple)
        else:
            arbiter.release()
        if imgui.is_item_deactivated_after_edit():
            hex_val = RgbaColor(new_tuple).to_hex(alpha=elem.alpha)
            elem.fire(
                ValueChanged(
                    scene_id=SceneId("__display__"),
                    element_id=ElementId(elem.id),
                    owner_id=ClientId("__display__"),
                    value=hex_val,
                )
            )
            arbiter.commit(RgbaColor.from_hex(hex_val).as_tuple(), hub_tuple)

    @staticmethod
    def _draw(elem: ColorPickerElement, resolved: Rgba) -> tuple[bool, Rgba]:
        """Draw the inline or full-picker variant, returning ``(changed, tuple)``.

        Both variants route their RGB channels through ``ColorChannelStrip``, whose
        per-channel fills scale with the value; the full-picker variant adds the SV
        square, hue bar, and hex readout. Each groups its sub-controls, so the
        caller's ``is_item_*`` reads see one item and one commit fires per release.
        """
        if elem.picker:
            return _PICKER.draw(elem, resolved)
        return _STRIP.draw(elem, resolved)
