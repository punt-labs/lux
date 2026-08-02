"""BoardSlot — the one board an applet holds, and whose board it keeps.

Two threads store into this: the warm-up, on its own worker thread at registration
and after every reconnect, and a click on another. They overlap by design — an
early click during warm-up is the case the warm-up exists for.

Both end in a store, and the read-modify-write in between takes as long as ``bd``
takes, so neither may simply assign. The rule instead is that the board from the
load which began last is kept, and a state holding no board never displaces one
that does — a maximum over a total order, so boards may be stored in any order
and the slot ends up holding the newest issues. Without it, a click whose ``bd``
failed while the warm-up was landing would write its empty state over the board
that had just arrived: the one cost the warm-up prevents.

The lock is never held across a load or a push: what runs inside it is a field
read, a comparison of two integers, and a field write, none of which can block.
The one other lock on this path — the push region's, in
:class:`~punt_lux.applets.board_glass.BoardGlass` — is the outer one, held while
a push reads this slot. Nothing here asks for it, so the nesting goes one way,
and one direction is not a cycle.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.loading_board import LoadingBoard
from punt_lux.applets.no_board import NoBoard

if TYPE_CHECKING:
    from punt_lux.applets.board_cache import CachedBoard

__all__ = ["BoardSlot"]


@final
class BoardSlot:
    """The board a click answers with, written by the click and the warm-up both."""

    _held: CachedBoard
    _lock: threading.Lock
    __slots__ = ("_held", "_lock")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._held = NoBoard(LoadingBoard())
        self._lock = threading.Lock()
        return self

    @property
    def held(self) -> CachedBoard:
        """The state a click answers from, as it stands now."""
        with self._lock:
            return self._held

    def store(self, loaded: CachedBoard) -> None:
        """Keep *loaded*, unless what is here holds a board whose load began later."""
        with self._lock:
            self._held = loaded.newer_of(self._held)
