"""BuiltBoard — a board that was built, and the place the load behind it began.

The two belong together from the moment the board exists. A rendered request
cannot say how old its issues are, and the place it was read at is exactly what
decides between two boards built by overlapping loads — so nothing carries one
without the other, and no later step has to remember to pair them up again.

This is what a read becomes once its issues are a board: the thing the applet
holds and, once it is holding it, shows. Holding it is a different job, with its
own answers about what the next click does — see
:class:`~punt_lux.applets.held_board.HeldBoard`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.applets.board_load import BoardRequest
    from punt_lux.applets.board_order import BoardOrder

__all__ = ["BuiltBoard"]


@final
class BuiltBoard:
    """A board ready to go up, carrying where the load that made it began."""

    _began: BoardOrder
    _request: BoardRequest
    __slots__ = ("_began", "_request")

    def __new__(cls, request: BoardRequest, began: BoardOrder) -> Self:
        self = super().__new__(cls)
        self._request = request
        self._began = began
        return self

    @property
    def began_at(self) -> BoardOrder:
        """Where the load that produced this board sits in the order they began."""
        return self._began

    @property
    def request(self) -> BoardRequest:
        """The board itself, for a click whose answer is this and not a stand-in."""
        return self._request
