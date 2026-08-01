"""BoardSlot — the one board an applet holds, and whose board it keeps.

Two threads store into this. The warm-up runs on its own worker thread when the
applet registers and again after every reconnect; a click runs on another. They
overlap by design: an early click during warm-up is the case the warm-up exists
for, so the two are expected to be in flight at once.

Both end in a store, and the read-modify-write in between takes as long as ``bd``
takes, so neither may simply assign. The rule instead is that the board which
finished loading last is the one kept, and a state holding no board never
displaces one that does. Under it a store is a maximum over a total order, so
boards may be stored in any order and the slot still ends up holding the newest
one. Without it, a click whose ``bd`` failed while the warm-up was landing would
write its empty state over the board that had just arrived, and the next click
would be cold again — the one cost the warm-up exists to prevent.

The lock is the whole of the coordination. There is one, it is taken nowhere
else, and it is never held across a load or a push: what runs inside it is a
field read, a comparison of two integers, and a field write. Nothing inside it
can block and there is no second lock to order it against, so no acquisition
order exists to get wrong.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

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
        self._held = NoBoard()
        self._lock = threading.Lock()
        return self

    @property
    def held(self) -> CachedBoard:
        """The state a click answers from, as it stands now."""
        with self._lock:
            return self._held

    def store(self, loaded: CachedBoard) -> None:
        """Keep *loaded*, unless what is here holds a board that loaded later."""
        with self._lock:
            self._held = loaded.newer_of(self._held)
