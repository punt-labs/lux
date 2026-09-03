"""BoardLoad — what a Beads board is made of, and the steps of putting one up.

A click does four separable things: it asks for the frame the board lives in,
reads the issues from ``bd``, builds the board they make, and pushes it. They are
separable because clicks combine them differently — a board already up gets the
first and the rest behind it, a board held gets a reload underneath it, and the
prefetch stops at the build, having no click to push anything for.

The reading raises rather than returning a reason, so no caller can push a
failure as though it were a board. That is the whole difference between the two
states in :mod:`punt_lux.applets.board_cache`: one shows the reason, the other
keeps the board it has and logs it. How a board reaches luxd is a different job
again, and lives in :class:`~punt_lux.applets.board_channel.BoardChannel`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.beads_source import BoardUnavailableError
from punt_lux.applets.board_channel import BoardChannel
from punt_lux.applets.board_order import BoardOrder
from punt_lux.applets.board_read import BoardRead
from punt_lux.apps.beads_result import BeadsFailure
from punt_lux.operations import RenderRequest, RenderTableRequest

if TYPE_CHECKING:
    from punt_lux.applets.beads_source import BeadsSource
    from punt_lux.applets.board_ops import BoardOps
    from punt_lux.applets.built_board import BuiltBoard
    from punt_lux.apps.beads_board import BeadsBoard

__all__ = ["BoardLoad", "BoardRequest"]

# What a board push carries, both of them requests the Hub installs: a table
# when there are issues to show, a plain scene when there is a message instead.
type BoardRequest = RenderTableRequest | RenderRequest


@final
class BoardLoad:
    """A board and where its issues come from: the work behind one menu entry."""

    _board: BeadsBoard
    _source: BeadsSource
    __slots__ = ("_board", "_source")

    def __new__(cls, board: BeadsBoard, source: BeadsSource) -> Self:
        self = super().__new__(cls)
        self._board = board
        self._source = source
        return self

    @property
    def frame_id(self) -> str:
        """The frame this board's issues render into."""
        return self._board.frame_id

    def issues(self) -> BoardRead:
        """Return the run ``bd`` completed, or raise the reason it could not.

        The whole run comes back rather than only its rows: where its time went
        is reported beside the board it produced, and it carries this load's
        place in the order loads began. That place is taken below rather than
        when the board is built, because a query's start fixes how old its rows
        will be.
        """
        began = BoardOrder.beginning()
        loaded = self._source.load()
        if isinstance(loaded.result, BeadsFailure):
            raise BoardUnavailableError(f"bd unavailable — {loaded.result.reason}")
        return BoardRead(loaded, began)

    def board(self, read: BoardRead) -> BuiltBoard:
        """Build the board a read makes, at the place that read began."""
        return read.built(self._board.request(read.result))

    def fresh(self) -> BuiltBoard:
        """Read the issues and build the board they make, as one step.

        They are separate above only for the click that times them separately.
        """
        return self.board(self.issues())

    def placeholder(self) -> BoardRequest:
        """The scene a click opens with when it has no board to show yet."""
        return self._board.starting()

    def unavailable(self, reason: str) -> BoardRequest:
        """The red message that says why there is no board to show."""
        return self._board.failure(reason)

    def push(self, client: BoardOps, request: BoardRequest) -> None:
        """Install a board through *client*, which logs whatever kept it off screen."""
        BoardChannel(client).send(request)
