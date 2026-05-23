# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for TextElement — handles style branches, color overrides, tooltips."""

from __future__ import annotations

from typing import ClassVar, Self

from imgui_bundle import ImVec4, imgui

from punt_lux.display.renderers._color import parse_hex_color
from punt_lux.protocol.elements.text import TextElement

__all__ = ["TextRenderer"]


type _Rgba = tuple[float, float, float, float]


class TextRenderer:
    """Render a TextElement, honouring style + color + tooltip semantics."""

    _STYLE_COLORS: ClassVar[dict[str, _Rgba]] = {
        "caption": (0.6, 0.6, 0.6, 1.0),
        "success": (0.2, 0.8, 0.2, 1.0),
        "error": (0.9, 0.2, 0.2, 1.0),
    }

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def render(self, elem: TextElement) -> None:
        color = parse_hex_color(elem.color) if elem.color else None
        # Unstyled text with a tooltip uses selectable() for hover detection.
        if elem.tooltip and not elem.style:
            self._render_with_tooltip(elem, color)
            return
        self._render_styled(elem, color)

    def _render_with_tooltip(self, elem: TextElement, color: _Rgba | None) -> None:
        if color is not None:
            imgui.push_style_color(imgui.Col_.text.value, ImVec4(*color))
        try:
            selected = False
            imgui.selectable(f"{elem.content}##{elem.id}", selected)
        finally:
            if color is not None:
                imgui.pop_style_color()
        if imgui.is_item_hovered(imgui.HoveredFlags_.for_tooltip.value):
            imgui.set_tooltip(elem.tooltip or "")

    def _render_styled(self, elem: TextElement, color: _Rgba | None) -> None:
        if color is not None:
            imgui.push_style_color(imgui.Col_.text.value, ImVec4(*color))
        try:
            self._emit_for_style(elem, color)
        finally:
            if color is not None:
                imgui.pop_style_color()

    def _emit_for_style(self, elem: TextElement, color: _Rgba | None) -> None:
        style = elem.style
        if style == "heading":
            imgui.separator_text(elem.content)
            return
        if style in self._STYLE_COLORS:
            self._emit_style_colored(elem.content, style, color)
            return
        if style == "code":
            imgui.indent(10.0)
            imgui.text(elem.content)
            imgui.unindent(10.0)
            return
        imgui.text_wrapped(elem.content)

    def _emit_style_colored(
        self, content: str, style: str | None, color: _Rgba | None
    ) -> None:
        if color is not None or style is None:
            imgui.text_wrapped(content)
            return
        rgba = self._STYLE_COLORS[style]
        imgui.push_style_color(imgui.Col_.text.value, ImVec4(*rgba))
        try:
            imgui.text_wrapped(content)
        finally:
            imgui.pop_style_color()
