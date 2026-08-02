"""BeadsService — the Beads menu entry a session owns, and what its click does.

luxd cannot run ``bd``: launchd starts it with no ``PATH``, no repository
credentials, and no repository working directory. The session has all three, so
the session owns the entry and services its own clicks — it loads the issues from
its shell and pushes the board to the Hub under its own identity.

Reading those issues is a query to a hosted database and it is the whole wait, so
the service never makes a user sit through one it could have run already: it
loads a board when it registers, holds the board from every click after that, and
answers each click with the one it is holding. The wait moves behind a real
board.

A click renders something either way. A ``bd`` that fails with no board held
renders the board's red message naming the reason; with a board held it leaves
that board standing and says why in the log.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.beads_source import BoardUnavailableError
from punt_lux.applets.board_load import BoardLoad
from punt_lux.applets.board_slot import BoardSlot
from punt_lux.applets.board_work import BoardWork
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


@final
class BeadsService:
    """A session's Beads entry: load this repository's issues and push its board.

    Its two loaders — the prefetch on one worker thread, a click on another —
    both store whole boards through :class:`BoardSlot`, which decides between
    them.
    """

    _load: BoardLoad
    _slot: BoardSlot
    __slots__ = ("_load", "_slot")

    def __new__(cls, load: BoardLoad) -> Self:
        self = super().__new__(cls)
        self._load = load
        self._slot = BoardSlot()
        return self

    @classmethod
    def for_repo(cls) -> Self:
        """Build the service for this repository's one board, loaded from ``bd``."""
        return cls(BoardLoad(BeadsBoard.for_repo(), BeadsBrowser()))

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
        scene, so the first click after one would otherwise be the cold click
        that waits on the whole query.

        Nothing is rendered here. A ``bd`` that would not run means only that the
        first click pays the wait, as it did before there was a prefetch, so it
        is a log line rather than a red scene. Anything else goes to the runner
        that called this, which is the boundary for the warm-up.
        """
        try:
            self._slot.store(HeldBoard(self._load.fresh()))
        except BoardUnavailableError as exc:
            logger.warning("no board could be loaded ahead of the first click: %s", exc)

    def acknowledge(self, client: LuxRestClient, latency: ClickLatency) -> None:
        """Put something on screen now, before any issue has been read.

        A click has to launch in the time a user reads as instant, and reading
        the issues cannot promise that. So the click's first act is not the
        query: it is raising the board's frame, which is the visible half of
        every click on this entry.

        What goes into that frame is the board this service is holding, or the
        placeholder when it is holding none — and the difference between those
        two answers is the whole of the difference between the two states, so
        they answer rather than being asked about.
        """
        self._slot.held.answer(BoardWork(self._load, client, latency))

    def service(self, client: LuxRestClient, latency: ClickLatency) -> None:
        """Answer a click: load the issues and push the board through ``client``.

        Runs after :meth:`acknowledge` has already made the frame visible, so
        this half may take as long as ``bd`` takes — and how long that was is
        reported either way, timed stage by stage when the user was watching a
        placeholder and as one figure when they were reading a board.

        Whatever loads is stored for the next click, so the wait is paid once.
        """
        work = BoardWork(self._load, client, latency)
        self._slot.store(self._slot.held.refreshed(work))
