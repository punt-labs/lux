"""BoardLoad — what a Beads board is made of, and the steps of putting one up.

A click does four separable things: it asks for the frame the board lives in,
reads the issues from ``bd``, builds the board they make, and pushes it. They are
separable because a click does them in different combinations. A click on a board
already on screen does the first and then the rest behind it; a click with a board
held in the applet shows that one and reloads underneath; the prefetch that runs
when the applet registers does the reading and the building and nothing else,
because there is no click yet to push anything for.

The reading raises rather than returning a reason, so that no caller can push a
failure as though it were a board. Which is the whole difference between the two
states in :mod:`punt_lux.applets.board_cache`: one shows the reason, the other
keeps the board it has and logs it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.beads_source import BoardUnavailableError
from punt_lux.apps.beads_result import BeadsFailure
from punt_lux.operations import FrameRaise, OpError, RenderRequest, RenderTableRequest

if TYPE_CHECKING:
    from punt_lux.applets.beads_source import BeadsSource
    from punt_lux.apps.beads_board import BeadsBoard
    from punt_lux.apps.beads_load import BeadsLoad
    from punt_lux.rest_client import LuxRestClient

logger = logging.getLogger(__name__)

__all__ = ["BoardLoad", "BoardRequest"]

# What every board push carries: a table when there are issues to show, a plain
# scene when there is a message instead. Both are requests the Hub installs.
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

    def showing(self, client: LuxRestClient) -> bool:
        """Bring the board's frame to the front; say whether the user has it already.

        Three outcomes collapse into two, and which way they collapse is the
        point. A frame that was raised means the board is in front of the user
        and nothing should be pushed over it. A raise that could not be answered
        at all — no display, a timed-out round trip — is reported and treated the
        same way: the board may well be up, and blanking a good board on the
        strength of a failed round trip is the worse of the two mistakes.
        """
        return self._raised(client.raise_frame(self._board.frame_id))

    @staticmethod
    def _raised(answer: FrameRaise | OpError) -> bool:
        """Read the display's answer, counting one it could not give as a yes."""
        if isinstance(answer, OpError):
            logger.warning("the board could not be raised: %s", answer.reason)
            return True
        return answer.raised

    def issues(self) -> BeadsLoad:
        """Return the run ``bd`` completed, or raise the reason it could not.

        The whole run comes back rather than only its rows, because how long it
        spent — spawning, waiting, parsing — is reported beside the board it
        produced.
        """
        loaded = self._source.load()
        if isinstance(loaded.result, BeadsFailure):
            raise BoardUnavailableError(f"bd unavailable — {loaded.result.reason}")
        return loaded

    def board(self, issues: BeadsLoad) -> BoardRequest:
        """Build the request that shows what a run read."""
        return self._board.request(issues.result)

    def fresh(self) -> BoardRequest:
        """Read the issues and build the board they make, as one step.

        The two are separate above because a click the user is waiting through
        times them separately. Nothing else needs them apart.
        """
        return self.board(self.issues())

    def placeholder(self) -> BoardRequest:
        """The scene a click opens with when it has no board to show yet."""
        return self._board.starting()

    def unavailable(self, reason: str) -> BoardRequest:
        """The red message that says why there is no board to show."""
        return self._board.failure(reason)

    def push(self, client: LuxRestClient, request: BoardRequest) -> None:
        """Install a board, or log why the Hub refused it.

        A table goes through the table route so the Hub *constructs* its live
        chrome; a message is a plain scene. A refusal has nowhere to be rendered —
        the render itself is what failed — so it is logged.
        """
        result = (
            client.render_table(request)
            if isinstance(request, RenderTableRequest)
            else client.render(request)
        )
        if isinstance(result, OpError):
            logger.error("beads board not shown: %s", result.reason)
