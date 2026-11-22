"""ImGuiTerminalRenderer — SPIKE adapter for ``TerminalElement``.

Paints the element's session in a child window: ``height`` points tall, or
the rest of the frame when ``height`` is 0. The session is looked up (and
started on first use) by name in ``RemoteSessions``. The render loop pumps
its daemon connection before painting; this adapter only draws.
"""

from __future__ import annotations

from typing import final

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.terminal.presenter import TerminalPresenter
from punt_lux.wire.model.elements.terminal import TerminalElement

__all__ = ["ImGuiTerminalRenderer"]


@final
class ImGuiTerminalRenderer(LeafRenderer[TerminalElement]):
    """Paint a ``TerminalElement``'s live session with the terminal font."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        TerminalPresenter.paint(self._elem)
