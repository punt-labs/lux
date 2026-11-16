# pyright: reportMissingModuleSource=false
"""ImGuiTerminalRenderer — SPIKE adapter for ``TerminalElement``.

Paints the session's GhosttyTerminalView in a child sized to the element's
``height`` (0 = the space left in the frame). The PTY itself is pumped once
per frame by the render loop via ``TerminalSessions.pump_all``.
"""

from __future__ import annotations

from typing import final

from imgui_bundle import ImVec2, imgui

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.terminal.sessions import TerminalSessions
from punt_lux.protocol.elements.terminal import TerminalElement

__all__ = ["ImGuiTerminalRenderer"]


@final
class ImGuiTerminalRenderer(LeafRenderer[TerminalElement]):
    """Paint a TerminalElement's live session via GhosttyTerminalView."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        elem = self._elem
        session = TerminalSessions.get(elem.session, elem.command)
        font = TerminalFonts.mono
        if font is not None:
            imgui.push_font(font, TerminalFonts.size)
        try:
            session.view.render_in_child(
                f"##term-{elem.id}", ImVec2(0, elem.height or 0)
            )
        finally:
            if font is not None:
                imgui.pop_font()


class TerminalFonts:
    """The monospace terminal font (CJK/emoji fallbacks merged), set at load."""

    mono: imgui.ImFont | None = None
    size: float = 14.0
