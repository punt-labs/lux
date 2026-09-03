"""AppletBoard — the one board an applet owns: loading it, keeping it, showing it.

Three things belong to the board rather than the menu entry above it: what
produces one (:class:`~punt_lux.applets.board_load.BoardLoad`), what keeps it
(:class:`~punt_lux.applets.board_slot.BoardSlot`), and what writes it to the
display (:class:`~punt_lux.applets.board_glass.BoardGlass`) -- one object.

What loaded is *kept* and then *shown*, never the other way round, and what
is shown is read from the slot inside the region that writes it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.board_glass import BoardGlass
from punt_lux.applets.board_work import BoardWork

if TYPE_CHECKING:
    from punt_lux.applets.board_cache import CachedBoard
    from punt_lux.applets.board_load import BoardLoad
    from punt_lux.applets.board_ops import BoardOps
    from punt_lux.applets.board_slot import BoardSlot
    from punt_lux.applets.built_board import BuiltBoard
    from punt_lux.applets.latency import ClickLatency

__all__ = ["AppletBoard"]


@final
class AppletBoard:
    """An applet's board: where it comes from, where it is kept, where it goes."""

    _glass: BoardGlass
    _load: BoardLoad
    _slot: BoardSlot
    __slots__ = ("_glass", "_load", "_slot")

    def __new__(cls, load: BoardLoad, slot: BoardSlot) -> Self:
        self = super().__new__(cls)
        self._load = load
        self._slot = slot
        self._glass = BoardGlass(slot)
        return self

    @property
    def held(self) -> CachedBoard:
        """The state a click answers from, as it stands now."""
        return self._slot.held

    @property
    def frame_id(self) -> str:
        """The frame this board renders into."""
        return self._load.frame_id

    def fresh(self) -> BuiltBoard:
        """Read the issues and build the board they make — the warm-up's load."""
        return self._load.fresh()

    def kept(self, loaded: CachedBoard) -> None:
        """Keep *loaded*, unless a later-started load is already here."""
        self._slot.store(loaded)

    def answers(self, work: BoardWork) -> None:
        """Fill the frame if the state holding it has anything to add.

        The Display already raised the frame locally at the click (DES-088);
        what is read here only decides whether to fill it, and is read again
        inside the push region, since a newer board can land between reads.
        """
        held = self._slot.held
        if held.answered(work):
            self.shows(work, held)

    def shows(self, work: BoardWork, mine: CachedBoard) -> None:
        """Put up the newer of what is kept and *mine*, one pusher at a time."""
        self._glass.shows(work, mine)

    def work(self, client: BoardOps, latency: ClickLatency) -> BoardWork:
        """One click's work against this board: what to load, and its clock."""
        return BoardWork(self._load, client, latency)
