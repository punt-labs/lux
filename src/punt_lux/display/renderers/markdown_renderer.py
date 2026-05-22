# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for MarkdownElement via imgui_md."""

from __future__ import annotations

from typing import Self

from imgui_bundle import imgui, imgui_md

from punt_lux.protocol.elements.markdown import MarkdownElement

__all__ = ["MarkdownRenderer"]


class MarkdownRenderer:
    """Render a MarkdownElement using imgui_md.render_unindented."""

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def render(self, elem: MarkdownElement) -> None:
        imgui.push_text_wrap_pos(0.0)
        try:
            imgui_md.render_unindented(elem.content)
        finally:
            imgui.pop_text_wrap_pos()
