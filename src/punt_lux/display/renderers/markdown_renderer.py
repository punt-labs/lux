# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for MarkdownElement via imgui_md.

Graceful degradation: when ``imgui_bundle.imgui_md`` is missing the
renderer falls back to ``imgui.text_unformatted`` so the renderers
package stays importable on stripped-down imgui-bundle builds.  Without
the fallback, a missing submodule cascades through
``element_renderer.py`` and crashes ``server.py`` at startup.
"""

from __future__ import annotations

from types import ModuleType
from typing import Self

from imgui_bundle import imgui

from punt_lux.protocol.elements.markdown import MarkdownElement

__all__ = ["MarkdownRenderer"]


# Lazy submodule load — see SpinnerRenderer for the same rationale.
# _imgui_md: ModuleType | None — None means "submodule unavailable; use
# the plain-text fallback".
_imgui_md: ModuleType | None
try:
    from imgui_bundle import imgui_md as _imgui_md_mod
except ImportError:
    _imgui_md = None
else:
    _imgui_md = _imgui_md_mod


class MarkdownRenderer:
    """Render a MarkdownElement using imgui_md.render_unindented."""

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def render(self, elem: MarkdownElement) -> None:
        if _imgui_md is None:
            imgui.text_unformatted(elem.content)
            return
        imgui.push_text_wrap_pos(0.0)
        try:
            _imgui_md.render_unindented(elem.content)
        finally:
            imgui.pop_text_wrap_pos()
