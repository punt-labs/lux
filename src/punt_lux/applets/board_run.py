"""BoardRun — a click's load, run so that one kind of failure comes out of it.

A load fails two ways and only one of them has anything to say to a user: ``bd``
could not be read, which has a reason, or something nobody modelled went wrong,
whose reason is a traceback and belongs in the log. What the state above does
next is the same either way — show the reason, or keep the board it has and log
it — so the second failure becomes the first here, once, rather than being
caught again in every state that runs a load.

The two shapes of run are the two shapes of click. A user watching a placeholder
waits through the query and the build as separate figures, because a slow query
and a slow build are different problems. A user reading a board waits through
none of it, so their reload is one figure with the push inside it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.beads_source import BoardUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.applets.board_work import BoardWork
    from punt_lux.applets.built_board import BuiltBoard

logger = logging.getLogger(__name__)

__all__ = ["BoardRun"]

# The two waits a user watching a placeholder sits through, named for what they
# are waiting on: the query to the hosted database, and the board built from
# what it returned.
_FETCHED = "fetched"
_BUILT = "built"

# What a click shows when the board could not be built for a reason nobody
# modelled: the reason itself is a traceback, which belongs in the log.
_UNBUILDABLE = "the beads board could not be built — see the session log"


@final
class BoardRun:
    """One click's load, run so that only a reason a user can read escapes it."""

    _work: BoardWork
    __slots__ = ("_work",)

    def __new__(cls, work: BoardWork) -> Self:
        self = super().__new__(cls)
        self._work = work
        return self

    def staged(self) -> BuiltBoard:
        """Read the issues and build their board, timing the two waits apart.

        Both are the user's wait — they are watching a placeholder through them
        — and they are different problems, so the line says which one it spent.
        """
        return self._reasoned(self._staged)

    def shown(self) -> BuiltBoard:
        """Read, build and push, for a user waiting through none of the three.

        The push is inside the run because it is inside the same figure: a
        reload behind a board somebody is already reading is one wait nobody
        has, not three they might.
        """
        return self._reasoned(self._shown)

    def _staged(self) -> BuiltBoard:
        """The load a user watches, each of its waits under its own figure."""
        with self._work.stage(_FETCHED):
            read = self._work.issues()
        with self._work.stage(_BUILT):
            return self._work.board(read)

    def _shown(self) -> BuiltBoard:
        """The load nobody watches, ending in the board it put up."""
        built = self._work.board(self._work.issues())
        built.push(self._work)
        return built

    @staticmethod
    def _reasoned(run: Callable[[], BuiltBoard]) -> BuiltBoard:
        """Run *run*, or raise the one failure a state above knows how to answer."""
        try:
            return run()
        except BoardUnavailableError:
            raise
        except Exception as exc:
            logger.exception("building the beads board failed")
            raise BoardUnavailableError(_UNBUILDABLE) from exc
