"""NoBoard — nothing has loaded, so the click opens on a blank and waits.

The state a session starts in, and the one it returns to while ``bd`` cannot be
read at all. A click from here is the cold one the warm-up exists to prevent: the
user watches "Loading issues…" for as long as the query takes, and every way it
can fail becomes something they see, or the menu simply looks broken.

Holding no board is not the same as having nothing to show, so this state holds
what goes up in place of one — the placeholder, or the reason the last read
failed, both :class:`~punt_lux.applets.blank_board.BlankBoard`s. Holding no
board, it never displaces one: see
:class:`~punt_lux.applets.board_order.BoardOrder` for the order that decides.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.beads_source import BoardUnavailableError
from punt_lux.applets.board_order import BoardOrder
from punt_lux.applets.board_run import BoardRun
from punt_lux.applets.held_board import HeldBoard
from punt_lux.applets.unreadable_board import UnreadableBoard

if TYPE_CHECKING:
    from punt_lux.applets.blank_board import BlankBoard
    from punt_lux.applets.board_cache import CachedBoard
    from punt_lux.applets.board_work import BoardWork

__all__ = ["NoBoard"]

# What the line says when a frame was already up: this state had nothing better
# to put in it, so the raise was the whole click. Its other answers are named by
# the blank it holds.
_RAISED = "frame already up"


@final
class NoBoard:
    """Nothing has loaded yet: the click opens on a blank and waits on a board."""

    _blank: BlankBoard
    __slots__ = ("_blank",)

    def __new__(cls, blank: BlankBoard) -> Self:
        self = super().__new__(cls)
        self._blank = blank
        return self

    @property
    def began_at(self) -> BoardOrder:
        """Before every load: this is the state there was before any began."""
        return BoardOrder.before_any_load()

    def newer_of(self, held: CachedBoard) -> CachedBoard:
        """Whatever is already held — a state with no board displaces nothing.

        A click whose ``bd`` failed ends here, and must not cost the applet a
        board that arrived while it was failing: the warm-up may have finished
        between this click reading the state and writing its result back.
        """
        return held

    def answered(self, work: BoardWork) -> bool:
        """Raise the frame, and fill it only if there was nothing in it.

        Whatever is in a frame already up beats the word "Loading". A raise
        that could not be answered reads as *not* up -- it establishes
        nothing about what is on screen, so the click fills the frame.
        """
        if work.showing():
            work.note(_RAISED)
            return False
        return True

    def refreshed(self, work: BoardWork) -> CachedBoard:
        """Load the board the user is waiting on, timing each stage of the wait.

        The run hands back one reason however it failed, and that reason is
        *held* rather than pushed from here: a message that comes from a state
        goes up the way a board does, so it cannot land over a board that
        arrived while this read was failing. It is not held as a *board*, so the
        next click starts cold rather than answering with a red message.
        """
        try:
            built = BoardRun(work).staged()
        except BoardUnavailableError as exc:
            return NoBoard(UnreadableBoard(str(exc)))
        return HeldBoard(built)

    def shows(self, work: BoardWork) -> None:
        """Put up the blank this state holds, having no board to put up."""
        work.push(self._blank.request(work))

    def said(self) -> str:
        """What the line calls that blank: the placeholder, or the last failure."""
        return self._blank.said()
