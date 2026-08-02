"""Whether a click has a board to show before its fresh one arrives.

The board comes from a query to a hosted database, and that query is the whole
wait: one measured click spent 4873 ms of its 4915 ms there. So the click stops
waiting on it — the applet keeps the last board that loaded and shows it at
once, replacing it when the fresh one lands.

That leaves two states, two classes rather than one class and a flag because
they differ in three ways. :class:`~punt_lux.applets.held_board.HeldBoard` fills
the frame a click raised whatever was in it, times its reload as one figure
nobody waits on, and survives a failed load; :class:`~punt_lux.applets.no_board.NoBoard`
fills a frame only when none came forward, times the wait its user is watching
stage by stage, and shows the reason in red when there is no board to keep.

Two loads can be in flight at once, so a state says where the load behind its
board began (:class:`~punt_lux.applets.board_order.BoardOrder`). That order
decides which board :class:`~punt_lux.applets.board_slot.BoardSlot` keeps *and*
what the display shows, since every push asks the state the slot holds what to
render, inside the region that writes it
(:class:`~punt_lux.applets.board_glass.BoardGlass`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from punt_lux.applets.board_order import BoardOrder
    from punt_lux.applets.board_work import BoardWork

__all__ = ["CachedBoard"]


class CachedBoard(Protocol):
    """What a click shows before its fresh load lands, and what happens after."""

    @property
    def began_at(self) -> BoardOrder:
        """Where the load behind this state's board sits in the order they began."""
        ...

    def newer_of(self, held: CachedBoard) -> CachedBoard:
        """Whichever of this and *held* holds the board whose load began last."""
        ...

    def answered(self, work: BoardWork) -> bool:
        """Raise the board's frame; say whether this state belongs in it."""
        ...

    def refreshed(self, work: BoardWork) -> CachedBoard:
        """Load the board behind that answer; return what is held. Show nothing."""
        ...

    def shows(self, work: BoardWork) -> None:
        """Put what this state has on the display — called inside the push region."""
        ...

    def said(self) -> str:
        """What the click's line calls that answer, once it is the one shown."""
        ...
