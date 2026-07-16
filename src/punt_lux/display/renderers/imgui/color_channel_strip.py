# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""ColorChannelStrip — the inline RGB(A) edit view with value-proportional fills.

Stock ``color_edit3`` draws each channel's DragInt with a fixed-width color
*marker* — a 3px tab at the left edge that only identifies the channel (red for
R, green for G, blue for B, grey for A). It never scales with the value, so R=216
and R=37 render an identical sliver. This strip replicates ColorEdit's layout — a
grouped row of editable DragInt channels plus a preview swatch and label — but
paints its own colored fill behind each channel scaled ``0..255 -> 0%..100%``, so
the fill reads the value.

The channels live inside one ``begin_group`` / ``end_group`` pair, exactly as
ColorEdit wraps its own components. That is load-bearing, not cosmetic: ImGui
forwards the active / deactivated / edited status of any child up to the group,
so a caller reading ``is_item_active`` / ``is_item_deactivated_after_edit`` after
the strip sees the whole control as one item — the reconciliation seam that reads
them is unchanged, and a release on any channel commits once.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, final

from imgui_bundle import ImVec2, ImVec4, imgui

if TYPE_CHECKING:
    from punt_lux.protocol.elements.color_picker import ColorPickerElement
    from punt_lux.protocol.elements.rgba_color import Rgba

__all__ = ["ColorChannelStrip"]

# Per-channel fill tints (R, G, B, A). The hues match ImGui's default channel
# markers; the muted alpha keeps the value text legible over the fill.
_FILLS: tuple[ImVec4, ...] = (
    ImVec4(0.94, 0.20, 0.20, 0.55),
    ImVec4(0.20, 0.85, 0.20, 0.55),
    ImVec4(0.30, 0.45, 0.95, 0.55),
    ImVec4(0.70, 0.70, 0.70, 0.55),
)
# AlwaysClamp clamps typed (Ctrl+click) input to the 0..255 min/max, not just
# dragging. Without it a typed 999 flows into the returned tuple and the fill
# paints past the field until RgbaColor clamps it at commit — the declared
# channel bounds must hold on every input path, not only the drag.
_CHANNEL_FLAGS = imgui.SliderFlags_.always_clamp.value
# A transparent frame lets the fill show; DragInt otherwise paints an opaque
# FrameBg over it.
_TRANSPARENT = ImVec4(0.0, 0.0, 0.0, 0.0)
_FRAME_COLS = (
    imgui.Col_.frame_bg,
    imgui.Col_.frame_bg_hovered,
    imgui.Col_.frame_bg_active,
)


@final
class ColorChannelStrip:
    """Draw the inline RGB(A) edit view with value-proportional per-channel fills."""

    __slots__ = ()

    def draw(self, elem: ColorPickerElement, resolved: Rgba) -> tuple[bool, Rgba]:
        """Draw the channel strip, returning ``(changed, arity-4 tuple)``.

        Mirrors ``color_edit3``'s reconciliation contract: one grouped item whose
        active / deactivate state the caller reads, ``changed`` an OR of the
        per-channel edits, and an arity-4 tuple. Under RGB the alpha is not
        editable, so the resolved alpha is carried through for tuple equality.
        """
        r, g, b, a = resolved
        count = 4 if elem.alpha else 3
        chans = [self._to_255(x) for x in (r, g, b, a)]

        imgui.push_id(elem.id)
        imgui.begin_group()
        style = imgui.get_style()
        spacing = style.item_inner_spacing.x
        frame_h = imgui.get_frame_height()
        # Reserve count spacings: count-1 between channels, one before the swatch.
        w_inputs = max(imgui.calc_item_width() - (frame_h + count * spacing), 1.0)

        for col in _FRAME_COLS:
            imgui.push_style_color(col.value, _TRANSPARENT)

        changed = False
        prev = 0.0
        for idx in range(count):
            if idx > 0:
                imgui.same_line(0.0, spacing)
            split = math.floor(w_inputs * (idx + 1) / count)
            width = max(split - prev, 1.0)
            prev = split
            imgui.set_next_item_width(width)
            pos = imgui.get_cursor_screen_pos()
            self._fill(pos, width, frame_h, chans[idx], _FILLS[idx])
            edited, chans[idx] = imgui.drag_int(
                f"##c{idx}", chans[idx], 1.0, 0, 255, flags=_CHANNEL_FLAGS
            )
            changed = changed or edited

        imgui.pop_style_color(len(_FRAME_COLS))
        self._preview(elem, chans, frame_h, spacing)
        imgui.end_group()
        imgui.pop_id()

        alpha = chans[3] / 255.0 if elem.alpha else a
        return (changed, (chans[0] / 255.0, chans[1] / 255.0, chans[2] / 255.0, alpha))

    @staticmethod
    def _fill(
        pos: ImVec2, width: float, height: float, value: int, tint: ImVec4
    ) -> None:
        """Paint the value-proportional colored fill behind one channel field."""
        fraction = value / 255.0
        if fraction <= 0.0:
            return
        # draw_list and frame rounding are frame-global; fetch, don't thread them.
        imgui.get_window_draw_list().add_rect_filled(
            pos,
            ImVec2(pos.x + width * fraction, pos.y + height),
            imgui.get_color_u32(tint),
            imgui.get_style().frame_rounding,
        )

    @staticmethod
    def _preview(
        elem: ColorPickerElement, chans: list[int], frame_h: float, spacing: float
    ) -> None:
        """Draw the color preview swatch and the label after the channel row."""
        imgui.same_line(0.0, spacing)
        alpha = chans[3] / 255.0 if elem.alpha else 1.0
        swatch = ImVec4(chans[0] / 255.0, chans[1] / 255.0, chans[2] / 255.0, alpha)
        imgui.color_button("##sw", swatch, 0, ImVec2(frame_h, frame_h))
        if elem.label:
            imgui.same_line(0.0, spacing)
            imgui.text(elem.label)

    @staticmethod
    def _to_255(value: float) -> int:
        """Return one ``[0, 1]`` channel as an 8-bit ``0..255`` int."""
        return max(0, min(255, round(value * 255.0)))
