# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for SpinnerElement — animated loading spinner via imspinner."""

from __future__ import annotations

from typing import Self

from imgui_bundle import ImVec4, imgui, imspinner

from punt_lux.display.renderers._color import parse_rgba
from punt_lux.protocol.elements.spinner import SpinnerElement

__all__ = ["SpinnerRenderer"]


class SpinnerRenderer:
    """Render a SpinnerElement using imspinner.spinner_ang_triple."""

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def render(self, elem: SpinnerElement) -> None:
        r, g, b, _a = parse_rgba(elem.color)
        color = ImVec4(r / 255.0, g / 255.0, b / 255.0, 1.0)
        im_color = imgui.ImColor(color)
        imspinner.spinner_ang_triple(
            f"##spin_{elem.id}",
            elem.radius,
            elem.radius * 0.6,
            elem.radius * 0.3,
            2.5,
            im_color,
            im_color,
            im_color,
        )
        if elem.label:
            imgui.same_line()
            imgui.text(elem.label)
