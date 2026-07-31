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
from typing import TYPE_CHECKING, Any, Protocol, Self, final

from punt_lux.apps.beads import BeadsBrowser
from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.operations import OpError, RenderRequest, RenderTableRequest

if TYPE_CHECKING:
    from punt_lux.rest_client import LuxRestClient

logger = logging.getLogger(__name__)

__all__ = ["BeadsService", "BeadsSource"]

# The callback id a click carries back, and the entry the display shows for it.
_CALLBACK_ID = "beads"
_LABEL = "Beads"


class BeadsSource(Protocol):
    """Where a board's rows come from — ``BeadsBrowser`` in the running session."""

    def load(
        self, *, all_issues: bool = False
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Return ``(issues, error)``: rows and ``None``, or ``[]`` and a reason.

        The rows are ``bd``'s own JSON objects, untyped at this boundary; the
        error is the documented absence of a failure, not a give-up.
        """
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
    def for_project(cls, project: str) -> Self:
        """Build the service for a repository's one beads board, loaded from ``bd``."""
        return cls(BeadsBoard.for_project(project), BeadsBrowser())

    @property
    def callback_id(self) -> str:
        """The id this session's menu clicks carry back to it."""
        return _CALLBACK_ID

    @property
    def label(self) -> str:
        """The entry the display shows under this session's submenu."""
        return _LABEL

    def service(self, client: LuxRestClient) -> None:
        """Answer a click: load the issues and push the board through ``client``.

        Runs on the session's own servicing thread, which is the last thing between
        a user's click and nothing happening — so an unforeseen failure becomes the
        board's red message rather than a traceback into a log. Expected failures
        (``bd`` missing, a bad repository) are already a message the loader
        reports; this catch covers the rest.
        """
        try:
            request = self._board.request(self._source.load())
        except Exception:
            logger.exception("building the beads board failed")
            request = self._board.failure(
                "the beads board could not be built — see the session log"
            )
        self._push(client, request)

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
