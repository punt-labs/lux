# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for SpinnerElement — animated loading spinner via imspinner.

Graceful degradation: when ``imgui_bundle.imspinner`` is missing (rare
imgui-bundle builds ship without it) the renderer falls back to an
animated ``[loading...]`` text marker.  The fallback keeps the basics
renderer package importable even on stripped-down environments — without
it, a missing optional submodule cascades through ``element_renderer.py``
and crashes ``server.py`` at startup.
"""

from __future__ import annotations

from types import ModuleType
from typing import Self

from imgui_bundle import ImVec4, imgui

from punt_lux.display.renderers._color import parse_rgba
from punt_lux.protocol.elements.spinner import SpinnerElement

__all__ = ["SpinnerRenderer"]


# Lazy submodule load: imspinner is an optional imgui-bundle submodule.
# A missing submodule would cascade through the renderers package and
# crash startup; the fallback path below keeps the renderer importable.
# imspinner: ModuleType | None — None means "submodule unavailable; use
# the text fallback".
_imspinner: ModuleType | None
try:
    from imgui_bundle import imspinner as _imspinner_mod
except ImportError:
    _imspinner = None
else:
    _imspinner = _imspinner_mod


class SpinnerRenderer:
    """Render a SpinnerElement using imspinner.spinner_ang_triple."""

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def render(self, elem: SpinnerElement) -> None:
        if _imspinner is None:
            self._render_fallback(elem)
            return
        r, g, b, _a = parse_rgba(elem.color)
        color = ImVec4(r / 255.0, g / 255.0, b / 255.0, 1.0)
        im_color = imgui.ImColor(color)
        _imspinner.spinner_ang_triple(
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

    def _render_fallback(self, elem: SpinnerElement) -> None:
        """Animated dots stand-in when imspinner is unavailable."""
        dots = "." * (int(imgui.get_time() * 3) % 4)
        imgui.text(f"[loading{dots}]")
        if elem.label:
            imgui.same_line()
            imgui.text(elem.label)
