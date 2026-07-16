# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""FullColorPicker — the SV-square + hue-bar picker with value-scaled RGB bars.

ImGui's ``color_picker3`` / ``color_picker4`` draws a saturation/value square, a
hue bar, and a stack of RGB/HSV/hex input rows. The RGB (and HSV) rows reuse
ColorEdit's fixed-width channel *markers* — a 3px tab that never scales with the
value, so R=68 and R=94 render an identical sliver. This composes the good half
of the stock widget (the SV square, the hue bar, and the markerless hex readout)
with ``ColorChannelStrip`` for the RGB channels, whose fills scale ``0..255 ->
0%..100%`` and actually read the value. The one stock row kept is the markerless
hex readout — the exact-value display the SV square cannot give.

The picker and the strip live inside one ``begin_group`` / ``end_group`` pair, so
the caller's ``is_item_*`` reads see every sub-control as one item — the
reconciliation seam is unchanged, and a release on any commits exactly once,
``ColorChannelStrip``'s group-aggregation contract extended over picker + strip.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from imgui_bundle import ImVec4, imgui

from punt_lux.display.renderers.imgui.color_channel_strip import ColorChannelStrip

if TYPE_CHECKING:
    from punt_lux.protocol.elements.color_picker import ColorPickerElement
    from punt_lux.protocol.elements.rgba_color import Rgba

__all__ = ["FullColorPicker"]

# A fixed picker width. The stock default sizes the SV square from the content
# region, which balloons the widget (the operator had to widen the window). 240px
# gives a comfortable square plus the hue and (optional) alpha bars.
_PICKER_WIDTH = 240.0
# DisplayHex selects only the hex readout row, dropping the fixed-marker RGB and
# HSV rows; NoSidePreview drops the duplicate current/reference swatch, since the
# channel strip draws its own preview swatch below. NoOptions disables the
# right-click context menu: without it, a user can right-click the picker and
# switch the display mode back to RGB or HSV, re-exposing the fixed-3px channel
# markers that DisplayHex exists to suppress. NoOptions locks the markerless
# hex-only display so the markers cannot return.
_PICKER_FLAGS = (
    imgui.ColorEditFlags_.display_hex.value
    | imgui.ColorEditFlags_.no_side_preview.value
    | imgui.ColorEditFlags_.no_options.value
)

# The strip is stateless — one shared instance for the RGB channel row.
_STRIP = ColorChannelStrip()


@final
class FullColorPicker:
    """Draw the full picker (SV square, hue bar, hex) with value-scaled RGB bars."""

    __slots__ = ()

    def draw(self, elem: ColorPickerElement, resolved: Rgba) -> tuple[bool, Rgba]:
        """Draw the picker plus channel strip, returning ``(changed, arity-4 tuple)``.

        The SV square / hue bar / hex row come from ``color_picker3`` /
        ``color_picker4``; the RGB bars come from ``ColorChannelStrip``, fed the
        picker's post-edit color so a channel drag overrides an SV/hue/hex edit in
        turn. ``changed`` ORs both sides; the single enclosing group aggregates the
        caller's ``is_item_*`` reads over every sub-control, so exactly one commit
        fires on any release.
        """
        r, g, b, a = resolved
        current = ImVec4(r, g, b, a)
        label = f"##picker{elem.id}"

        imgui.push_item_width(_PICKER_WIDTH)
        imgui.begin_group()
        if elem.alpha:
            pick_changed, new = imgui.color_picker4(label, current, _PICKER_FLAGS)
        else:
            pick_changed, new = imgui.color_picker3(label, current, _PICKER_FLAGS)
        # Under RGB the alpha is not editable, so carry the resolved alpha through
        # to keep arity 4 and tuple equality well-defined for reconciliation.
        alpha = float(new[3]) if elem.alpha else a
        picked: Rgba = (float(new[0]), float(new[1]), float(new[2]), alpha)
        strip_changed, combined = _STRIP.draw(elem, picked)
        imgui.end_group()
        imgui.pop_item_width()

        return (pick_changed or strip_changed, combined)
