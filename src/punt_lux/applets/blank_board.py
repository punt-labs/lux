"""BlankBoard — what a state holding no board shows where the board would be.

Holding no board is not the same as having nothing to say. A session that has not
read its issues yet shows the placeholder it is reading them behind; a session
whose ``bd`` could not be read shows the reason in red, because a menu entry that
produces nothing visible reads as broken rather than as busy.

Those are two answers to one question, so they are two small states rather than a
reason that is sometimes empty — :class:`~punt_lux.applets.loading_board.LoadingBoard`
and :class:`~punt_lux.applets.unreadable_board.UnreadableBoard`. What holds one is
:class:`~punt_lux.applets.no_board.NoBoard`, and what puts it on the display is the
push region in :class:`~punt_lux.applets.board_glass.BoardGlass` — which pushes it
only while the slot is still holding no board, so a blank can never land over a
board another thread has just loaded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from punt_lux.applets.board_load import BoardRequest
    from punt_lux.applets.board_work import BoardWork

__all__ = ["BlankBoard"]


class BlankBoard(Protocol):
    """What goes up in place of a board, and what the click's line calls it."""

    def request(self, work: BoardWork) -> BoardRequest:
        """The scene to install where a board would be."""
        ...

    def said(self) -> str:
        """What a click answering with this says it answered with."""
        ...
