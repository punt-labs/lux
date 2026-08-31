"""BoardChannel — the Hub end of a board: the routes in, and the ways in.

Everything a click sends the Hub goes through here: the raise that asks for the
frame, and the push that installs a board in it. Both can fail, and neither
failure is worth raising at the caller, because by the time a board is being sent
the expensive part is already done — the query behind it has been paid for, and
losing the board over a round trip that did not land would mean paying it again.

So this is where a failure to reach luxd stops. What the caller gets back is what
it can act on: whether the frame is up, and nothing at all from a push.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.operations import OpError, RenderTableRequest
from punt_lux.rest_transport import HubUnavailableError

if TYPE_CHECKING:
    from punt_lux.applets.board_load import BoardRequest
    from punt_lux.applets.board_ops import BoardOps
    from punt_lux.operations.models.scene_results import SceneShown

logger = logging.getLogger(__name__)

__all__ = ["BoardChannel"]


@final
class BoardChannel:
    """One click's line to the Hub, and the log every failure on it ends in."""

    _client: BoardOps
    __slots__ = ("_client",)

    def __new__(cls, client: BoardOps) -> Self:
        self = super().__new__(cls)
        self._client = client
        return self

    def raised(self, frame_id: str) -> bool:
        """Bring a frame to the front; say whether the user has it already.

        Only a real ``raised: true`` says the board is in front of the user. A
        round trip that could not be answered at all establishes nothing about
        what is on screen, so it is treated as *not* raised rather than assumed
        — trusting it would skip the push that fills or refreshes the frame.
        """
        answer = self._client.raise_frame(frame_id)
        if isinstance(answer, OpError):
            logger.warning("the board could not be raised: %s", answer.reason)
            return False
        return answer.raised

    def send(self, request: BoardRequest) -> None:
        """Install a board, or log why it did not land.

        A refusal has nowhere to be rendered — the render itself is what failed.
        A Hub that could not be reached is the same fact arriving as an
        exception. Neither is worth what a raise would cost the caller, which is
        the board it has just spent seconds loading.
        """
        try:
            self._reported(self._installed(request))
        except HubUnavailableError as exc:
            logger.warning("beads board not shown — luxd unreachable: %s", exc)

    def _installed(self, request: BoardRequest) -> SceneShown | OpError:
        """Send the board down whichever route its kind belongs to.

        A table goes through the table route so the Hub *constructs* its live
        chrome; a message is a plain scene.
        """
        if isinstance(request, RenderTableRequest):
            return self._client.render_table(request)
        return self._client.render(request)

    @staticmethod
    def _reported(result: SceneShown | OpError) -> None:
        """Say why the Hub would not install a board it did receive."""
        if isinstance(result, OpError):
            logger.error("beads board not shown: %s", result.reason)
