"""AppletBoard — the one board an applet owns: loading it, keeping it, showing it.

Three things belong to the board rather than to the menu entry above it: what
produces a board (:class:`~punt_lux.applets.board_load.BoardLoad`), what keeps
the one the applet is holding (:class:`~punt_lux.applets.board_slot.BoardSlot`),
and what writes it to the display
(:class:`~punt_lux.applets.board_glass.BoardGlass`). They travel together through
every phase of every click, so they are one object; what is left above is a
service that knows only the three phases of a click.

The order between the last two is the whole of this module's contract: what
loaded is *kept* and then *shown*, never the other way round, and what is shown
is read from the slot inside the region that writes it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.board_glass import BoardGlass
from punt_lux.applets.board_work import BoardWork

if TYPE_CHECKING:
    from punt_lux.applets.board_cache import CachedBoard
    from punt_lux.applets.board_load import BoardLoad
    from punt_lux.applets.board_slot import BoardSlot
    from punt_lux.applets.built_board import BuiltBoard
    from punt_lux.applets.latency import ClickLatency
    from punt_lux.rest_client import LuxRestClient

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

    def fresh(self) -> BuiltBoard:
        """Read the issues and build the board they make — the warm-up's load."""
        return self._load.fresh()

    def kept(self, loaded: CachedBoard) -> None:
        """Keep *loaded*, unless a board whose load began later is already here."""
        self._slot.store(loaded)

    def answers(self, work: BoardWork) -> None:
        """Raise the frame, and fill it if the state holding it has anything to add.

        What the state read here decides is only whether to fill the frame; what
        goes *in* it is read again inside the region, because the raise is a
        round trip and a newer board can land inside one.
        """
        held = self._slot.held
        if held.answered(work):
            self.shows(work, held)

    def shows(self, work: BoardWork, mine: CachedBoard) -> None:
        """Put up the newer of what is kept and *mine*, one pusher at a time."""
        self._glass.shows(work, mine)

    def work(self, client: LuxRestClient, latency: ClickLatency) -> BoardWork:
        """One click's work against this board: what to load, and its clock."""
        return BoardWork(self._load, client, latency)
