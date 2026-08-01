"""Whether a click has a board to show before its fresh one arrives.

The board comes from a query to a hosted database, and that query is the whole
wait: on the author's machine one measured click spent 4873 ms of its 4915 ms
there. Nothing here makes the query faster, so the click stops waiting on it. The
applet keeps the last board that loaded — read once when the applet registers,
and again behind every click — and a click shows that board straight away, then
replaces it in place when the fresh one lands.

That leaves two states, and they differ in three ways, which is why they are two
classes rather than one class and a flag:

- what the click answers with: a placeholder, or the board already held —
  :class:`~punt_lux.applets.no_board.NoBoard` against
  :class:`~punt_lux.applets.held_board.HeldBoard`;
- how the load behind it is timed: stage by stage when the user is watching a
  placeholder, one figure when they are reading a board and waiting on nothing;
- what a failed load does: replace the placeholder with the reason in red, or
  leave the board where it is and log why it was not replaced.

Two loads can be in flight at once — the warm-up on one worker thread and an
early click on another, which is the case the warm-up exists for — so a state
also says where the board it holds sits in the order boards finished loading.
Boards are numbered from zero as they load; a state holding none sits at -1,
before them all. That numbering is what lets whoever stores last keep the newer
board rather than the later-written one, in
:class:`~punt_lux.applets.board_slot.BoardSlot` — the only place either state is
stored.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from punt_lux.applets.board_load import BoardRequest
    from punt_lux.applets.board_work import BoardWork

__all__ = ["CachedBoard"]


class CachedBoard(Protocol):
    """What a click shows before its fresh load lands, and what happens after."""

    @property
    def loaded_at(self) -> int:
        """Where the board this holds sits in the order boards loaded in."""
        ...

    def newer_of(self, held: CachedBoard) -> CachedBoard:
        """Whichever of this state and *held* holds the board that loaded last."""
        ...

    def opening(self, work: BoardWork) -> BoardRequest:
        """The request the click's answer puts up, before anything has loaded."""
        ...

    def refreshed(self, work: BoardWork) -> CachedBoard:
        """Load the board behind that answer; return what is held afterwards."""
        ...
