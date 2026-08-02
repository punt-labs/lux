"""BoardGlass — the board on screen, and the one region a push of one runs in.

What the applet holds and what the user is looking at are two different things.
The first lives in :class:`~punt_lux.applets.board_slot.BoardSlot` and is settled
by the order loads began in. The second lives at the far end of a round trip to
luxd, and it is settled by whichever push wrote last — which, left to itself, is
settled by nothing at all. Two pushers can begin in one order and land in the
other, leaving the screen showing a board the applet has already replaced, and
nothing repairs it until somebody clicks again.

So every push of board content runs here, and the region has two halves that are
inert apart:

- the lock is held **across the socket write**, so at most one push is settled
  and unlanded at a time and the writes land in the order they were taken;
- the state to show is read from the slot **inside** that lock, so what lands is
  what the applet holds now rather than what the pusher captured before it
  raised the frame.

Serialising the writes without re-reading lands captured boards in order but
lands stale ones; re-reading without serialising reads the right board and then
races to write it. Both together are what make the screen monotone. A place
comparison on top of them would be dead code: the slot never goes backwards and
the glass never runs ahead of the slot, so a board read from the slot inside this
region is never older than the one already showing, and a counter that skipped
such a push could never admit place zero either — it would suppress the first
placeholder of a session outright.

**Lock order.** This region's lock is the outer one: it is held while the slot's
is taken, and no holder of the slot's lock ever asks for this one. One direction
is not a cycle, so the pair is deadlock-free by acquisition order.

One boundary stays open, deliberately. The slot's lock is not held across the
write — the write is a socket round trip — so a store landing between the read
and the write leaves the display one generation behind the slot. That is ordinary
staleness, indistinguishable from a load that landed a millisecond after the push
instead of before it, and closing it would cost a socket round trip under the
slot's lock.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.applets.board_cache import CachedBoard
    from punt_lux.applets.board_slot import BoardSlot
    from punt_lux.applets.board_work import BoardWork

__all__ = ["BoardGlass"]


@final
class BoardGlass:
    """The display's copy of the board, written by one pusher at a time."""

    _lock: threading.Lock
    _slot: BoardSlot
    __slots__ = ("_lock", "_slot")

    def __new__(cls, slot: BoardSlot) -> Self:
        self = super().__new__(cls)
        self._slot = slot
        self._lock = threading.Lock()
        return self

    def shows(self, work: BoardWork, mine: CachedBoard) -> None:
        """Put up the newer of what the slot holds and *mine*, and land it here.

        *mine* is what this pusher would have shown — the board it just stored,
        or the blank it would put up in place of one. It wins only if the slot
        holds nothing newer, which is why a placeholder cannot blank a board
        that arrived while this click was raising the frame, and why a failure
        message cannot either. On a cold click the slot holds that same blank,
        so the placeholder goes up and the first one of a session still appears.

        The line is noted here rather than by the caller, because what a click
        says it answered with has to be what actually went up.
        """
        with self._lock:
            shown = self._slot.held.newer_of(mine)
            work.note(shown.said())
            shown.shows(work)
