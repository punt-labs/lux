# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for ColorPickerElement — a commit-on-idle RGB(A) color picker.

While idle the color is synced to the Hub-authoritative ``elem.value`` (a hex
string parsed to a tuple); while a sub-control is dragged the local buffer wins
and a Hub-driven value is deferred. Exactly one ``ValueChanged`` fires when a
sub-control releases (via ``is_item_deactivated_after_edit``), never per drag
frame — so a Hub re-push landing mid-drag cannot clobber the color under the
cursor. The commit fire is wrapped for remote dispatch so the interaction runs
on the Hub, not locally.

The arbiter keeps the buffer/commit-echo slots as RGBA tuples; the wire fire
carries a hex string. On release the *quantized* (8-bit round-tripped) tuple is
committed, so it bit-equals the eventual echo and there is no full-precision→
8-bit color pop while the optimistic-echo window is open.
"""

from __future__ import annotations

from typing import Self, final

from imgui_bundle import ImVec4, imgui

from punt_lux.display.renderers.imgui.color_picker_selection import ColorPickerArbiter
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.color_picker import ColorPickerElement
from punt_lux.protocol.elements.rgba_color import Rgba, RgbaColor
from punt_lux.scene import WidgetState
from punt_lux.tracing import trace

__all__ = ["ColorPickerRenderer"]


@final
class ColorPickerRenderer:
    """Render a ColorPickerElement under the commit-on-idle rule.

    Holds the per-scene ``WidgetState`` (re-threaded on a scene switch) and
    builds a fresh ``ColorPickerArbiter`` per element per frame; the arbiter owns
    the buffer/commit-echo slots, so this class stays a thin ImGui seam. The
    commit fire routes through the element's handler registry, wrapped for
    remote dispatch, so the interaction runs on the Hub, not locally.
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
        arbiter = ColorPickerArbiter(self._widget_state, elem.id)
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
        """Draw the edit/picker RGB/RGBA variant, returning ``(changed, tuple)``.

        ImGui works in an ``ImVec4``; the returned color is normalized back to an
        arity-4 tuple. Under an RGB variant the alpha channel is not editable, so
        the resolved alpha (opaque for a ``#RRGGBB`` value) is carried through —
        keeping the carrier arity 4 so tuple equality stays well-defined.
        """
        r, g, b, a = resolved
        current = ImVec4(r, g, b, a)
        label = f"{elem.label}##{elem.id}"
        if elem.picker:
            changed, new = (
                imgui.color_picker4(label, current)
                if elem.alpha
                else imgui.color_picker3(label, current)
            )
        else:
            changed, new = (
                imgui.color_edit4(label, current)
                if elem.alpha
                else imgui.color_edit3(label, current)
            )
        alpha = float(new[3]) if elem.alpha else a
        return (changed, (float(new[0]), float(new[1]), float(new[2]), alpha))
