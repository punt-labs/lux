"""A terminal paint boundary keeps malformed replicas from aborting the frame."""

from __future__ import annotations

from typing import TYPE_CHECKING

from imgui_bundle import ImVec2, imgui

from punt_lux.display.terminal.font import TerminalFont
from punt_lux.display.terminal.remote_sessions import RemoteSessions
from punt_lux.wire.stream.control_fields import ControlError

if TYPE_CHECKING:
    from punt_lux.display.terminal.remote import RemoteSession
    from punt_lux.wire.model.elements.terminal import TerminalElement


class TerminalPresenter:
    @staticmethod
    def paint(elem: TerminalElement) -> None:
        try:
            session = RemoteSessions.get(elem.session, elem.command)
            session.mark_shown()  # this frame paints it: keep the loop awake
            TerminalPresenter._render(elem, session)
        except ControlError as error:
            imgui.text_wrapped(f"Terminal unavailable: {error}")

    @staticmethod
    def _render(elem: TerminalElement, session: RemoteSession) -> None:
        font = TerminalFont.font
        if font is not None:
            imgui.push_font(font, TerminalFont.size)
        try:
            session.render_in_child(f"##terminal-{elem.id}", ImVec2(0, elem.height))
        finally:
            if font is not None:
                imgui.pop_font()
