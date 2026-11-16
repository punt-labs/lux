# pyright: reportMissingModuleSource=false
"""ImGuiTerminalRenderer — SPIKE adapter for ``TerminalElement``.

Paints the element's session in a child window: ``height`` points tall, or
the rest of the frame when ``height`` is 0. The session is looked up (and
started on first use) by name in ``TerminalSessions``; the render loop pumps
its PTY each frame before painting, so this adapter only draws (ADR-0006).
"""

from __future__ import annotations

from typing import final

from imgui_bundle import ImVec2, imgui

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.terminal.font import TerminalFont
from punt_lux.display.terminal.sessions import TerminalSessions
from punt_lux.protocol.elements.terminal import TerminalElement

__all__ = ["ImGuiTerminalRenderer"]


@final
class ImGuiTerminalRenderer(LeafRenderer[TerminalElement]):
    """Paint a ``TerminalElement``'s live session with the terminal font."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        elem = self._elem
        session = TerminalSessions.get(elem.session, elem.command)
        font = TerminalFont.font
        if font is not None:
            imgui.push_font(font, TerminalFont.size)
        try:
            session.view.render_in_child(
                f"##terminal-{elem.id}", ImVec2(0, elem.height)
            )
        finally:
            if font is not None:
                imgui.pop_font()
