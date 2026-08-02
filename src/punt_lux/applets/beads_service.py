"""BeadsService — the Beads menu entry a session owns, and what its click does.

luxd cannot run ``bd``: launchd starts it with no ``PATH``, no repository
credentials and no working directory. The session has all three, so it owns the
entry and services its own clicks — loading the issues from its shell and
pushing the board to the Hub under its own identity.

Reading those issues is a query to a hosted database and it is the whole wait, so
the service never makes a user sit through one it could have run already: it
loads a board when it registers and answers every click after that with the one
it holds, moving the wait behind a real board.

A click renders something either way, and always in one order: whatever it loaded
is kept, and then the display is shown what the applet holds. A push before the
store would show issues the applet had not kept, or a board the slot refused.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.applet_board import AppletBoard
from punt_lux.applets.beads_source import BoardUnavailableError
from punt_lux.applets.board_load import BoardLoad
from punt_lux.applets.board_slot import BoardSlot
from punt_lux.applets.held_board import HeldBoard
from punt_lux.apps.beads import BeadsBrowser
from punt_lux.apps.beads_board import BeadsBoard

if TYPE_CHECKING:
    from punt_lux.applets.latency import ClickLatency
    from punt_lux.rest_client import LuxRestClient

logger = logging.getLogger(__name__)

__all__ = ["BeadsService"]

# The callback id a click carries back, and the entry the display shows for it.
_CALLBACK_ID = "beads"
_LABEL = "Beads"

# The round trip that puts a board on screen, timed apart from the load in front
# of it: a slow query and a slow Hub are different problems.
_PUSHED = "pushed"


@final
class BeadsService:
    """A session's Beads entry: load this repository's issues and push its board.

    Its two loaders — the prefetch on one worker thread, a click on another —
    both go through the applet's board, which decides which of two they keep and
    what the user ends up looking at.
    """

    _board: AppletBoard
    __slots__ = ("_board",)

    def __new__(cls, board: AppletBoard) -> Self:
        self = super().__new__(cls)
        self._board = board
        return self

    @classmethod
    def for_repo(cls) -> Self:
        """Build the service for this repository's one board, loaded from ``bd``."""
        load = BoardLoad(BeadsBoard.for_repo(), BeadsBrowser())
        return cls(AppletBoard(load, BoardSlot()))

    @property
    def callback_id(self) -> str:
        """The id this session's menu clicks carry back to it."""
        return _CALLBACK_ID

    @property
    def label(self) -> str:
        """The entry the display shows under this session's submenu."""
        return _LABEL

    def prefetch(self) -> None:
        """Load a board before anyone clicks, so the first click has one to show.

        Run once the entry is registered and again after every reconnect, which
        is when a board is most worth having: a Hub that just restarted holds no
        scene, so the first click after one would otherwise wait on the query.

        Nothing is rendered here. A ``bd`` that would not run means only that the
        first click pays that wait, as it did before there was a prefetch, so it
        is a log line rather than a red scene.
        """
        try:
            self._board.kept(HeldBoard(self._board.fresh()))
        except BoardUnavailableError as exc:
            logger.warning("no board could be loaded ahead of the first click: %s", exc)

    def acknowledge(self, client: LuxRestClient, latency: ClickLatency) -> None:
        """Put something on screen now, before any issue has been read.

        A click has to launch in the time a user reads as instant, and reading
        the issues cannot promise that. So the click's first act is not the
        query: it is raising the board's frame — the visible half of every click
        here — and filling it with the board held, or the blank held instead.
        """
        self._board.answers(self._board.work(client, latency))

    def service(self, client: LuxRestClient, latency: ClickLatency) -> None:
        """Answer a click: load the issues, keep what loaded, and show it.

        Runs after :meth:`acknowledge` has made the frame visible, so this half
        may take as long as ``bd`` takes — timed stage by stage when the user is
        watching a placeholder, as one figure when they are reading a board.

        Whatever loads is kept for the next click, so the wait is paid once, and
        kept *before* it is shown. What goes up is then read from the slot
        rather than passed along from here: a load that began earlier and
        returned later has been refused by then, and must not reach the screen.
        """
        work = self._board.work(client, latency)
        loaded = self._board.held.refreshed(work)
        self._board.kept(loaded)
        with work.stage(_PUSHED):
            self._board.shows(work, loaded)
