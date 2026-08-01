"""BeadsService — the Beads menu entry a session owns, and what its click does.

luxd cannot run ``bd``: launchd starts it with no ``PATH``, no repository
credentials, and no repository working directory. The session has all three, so
the session owns the entry and services its own clicks — it loads the issues from
its shell and pushes the board to the Hub under its own identity.

A click renders something either way. A ``bd`` that fails renders the board's red
message naming the reason, so the user sees what went wrong in the window where
they clicked rather than in a log they will not read.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, Self, final

from punt_lux.apps.beads import BeadsBrowser
from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.apps.beads_result import BeadsResult
from punt_lux.operations import OpError, RenderRequest, RenderTableRequest

if TYPE_CHECKING:
    from punt_lux.applets.latency import ClickLatency
    from punt_lux.rest_client import LuxRestClient

logger = logging.getLogger(__name__)

__all__ = ["BeadsService", "BeadsSource"]

# The callback id a click carries back, and the entry the display shows for it.
_CALLBACK_ID = "beads"
_LABEL = "Beads"

# The three stages behind the answer, named for what the user is waiting on:
# the query to the hosted database, the board built from what it returned, and
# the round trip that puts that board on screen.
_FETCHED = "fetched"
_BUILT = "built"
_PUSHED = "pushed"


class BeadsSource(Protocol):
    """Where a board's rows come from — ``BeadsBrowser`` in the running session."""

    def load(self, *, all_issues: bool = False) -> BeadsResult:
        """Return the issues that were read, or the reason none were."""
        ...


@final
class BeadsService:
    """A session's Beads entry: load this repository's issues and push its board."""

    _board: BeadsBoard
    _source: BeadsSource
    __slots__ = ("_board", "_source")

    def __new__(cls, board: BeadsBoard, source: BeadsSource) -> Self:
        self = super().__new__(cls)
        self._board = board
        self._source = source
        return self

    @classmethod
    def for_repo(cls) -> Self:
        """Build the service for this repository's one board, loaded from ``bd``."""
        return cls(BeadsBoard.for_repo(), BeadsBrowser())

    @property
    def callback_id(self) -> str:
        """The id this session's menu clicks carry back to it."""
        return _CALLBACK_ID

    @property
    def label(self) -> str:
        """The entry the display shows under this session's submenu."""
        return _LABEL

    def acknowledge(self, client: LuxRestClient) -> None:
        """Put something on screen now, before any issue has been read.

        A click has to launch in the time a user reads as instant, and reading the
        issues cannot promise that — it is a query to a hosted database. So the
        click's first act is not the query: it is raising the board's frame, which
        is the whole answer in the common case, where the board is already up and
        the user is asking to look at it again.

        A frame that is not up gets the placeholder instead, so the cold click
        opens a window immediately and fills it when the rows arrive. A raise that
        could not be answered at all — no display, a timed-out round trip — pushes
        nothing: the board is about to be pushed anyway, and replacing a good board
        with "Loading" on the strength of a failed round trip would be a step
        backwards for the user.
        """
        raised = client.raise_frame(self._board.frame_id)
        if isinstance(raised, OpError):
            logger.warning("the board could not be raised: %s", raised.reason)
            return
        if not raised.raised:
            self._push(client, self._board.starting())

    def service(self, client: LuxRestClient, latency: ClickLatency) -> None:
        """Answer a click: load the issues and push the board through ``client``.

        Runs after :meth:`acknowledge` has already made the frame visible, so this
        half may take as long as ``bd`` takes. Every failure this side of the Hub
        becomes something the user can see: a load that fails renders its reason in
        red rather than leaving the board blank, and a push the Hub refuses is
        reported — there is nowhere left to render a message about the render
        itself.

        Because it may take as long as ``bd`` takes, it says how long it took:
        each of the three things it does is timed separately into ``latency``, so
        a board that was slow to arrive names which of them was slow rather than
        leaving the query and the round trip to be told apart by guesswork.
        """
        request = self._request(latency)
        with latency.stage(_PUSHED):
            self._push(client, request)

    def _request(self, latency: ClickLatency) -> RenderTableRequest | RenderRequest:
        """Build the board's request, turning any failure into a showable one.

        The loader already reports its expected failures — ``bd`` missing, a bad
        repository — as a reason to render. This covers the rest, because the
        session's servicing thread is the last thing between a user's click and
        nothing happening at all. A failure that lands here is timed into
        whichever stage it happened in and none of the ones after it, so the line
        for a broken click says how far the click got.
        """
        try:
            with latency.stage(_FETCHED):
                loaded = self._source.load()
            with latency.stage(_BUILT):
                return self._board.request(loaded)
        except Exception:
            logger.exception("building the beads board failed")
            return self._board.failure(
                "the beads board could not be built — see the session log"
            )

    def _push(
        self, client: LuxRestClient, request: RenderTableRequest | RenderRequest
    ) -> None:
        """Install the board, or log why the Hub refused it.

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
