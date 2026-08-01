"""Whether a click has a board to show before its fresh one arrives.

The board comes from a query to a hosted database, and that query is the whole
wait: on the author's machine one measured click spent 4873 ms of its 4915 ms
there. Nothing here makes the query faster, so the click stops waiting on it. The
applet keeps the last board that loaded — read once when the applet registers,
and again behind every click — and a click shows that board straight away, then
replaces it in place when the fresh one lands.

That leaves two states, and they differ in three ways, which is why they are two
classes rather than one class and a flag:

- what the click answers with: a placeholder, or the board already held;
- how the load behind it is timed: stage by stage when the user is watching a
  placeholder, one figure when they are reading a board and waiting on nothing;
- what a failed load does: replace the placeholder with the reason in red, or
  leave the board where it is and log why it was not replaced.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, Self, final

from punt_lux.applets.beads_source import BoardUnavailableError

if TYPE_CHECKING:
    from punt_lux.applets.board_load import BoardRequest
    from punt_lux.applets.board_work import BoardWork

logger = logging.getLogger(__name__)

__all__ = ["CachedBoard", "HeldBoard", "NoBoard"]

# The stages of a load the user is waiting through, named for what they are
# waiting on: the query to the hosted database, the board built from what it
# returned, and the round trip that puts that board on screen.
_FETCHED = "fetched"
_BUILT = "built"
_PUSHED = "pushed"

# The same work when the user is not waiting on it, under one figure: they have a
# board to read while it runs, and no stage of it is their problem.
_REFRESHED = "refreshed"

# What the click's line says its answer was, when the answer was the real board.
_FROM_CACHE = "cached board"

# What a click shows when the board could not be built for a reason nobody
# modelled: the reason itself is a traceback, which belongs in the log.
_UNBUILDABLE = "the beads board could not be built — see the session log"


class CachedBoard(Protocol):
    """What a click shows before its fresh load lands, and what happens after."""

    def opening(self, work: BoardWork) -> BoardRequest:
        """The request the click's answer puts up, before anything has loaded."""
        ...

    def refreshed(self, work: BoardWork) -> CachedBoard:
        """Load the board behind that answer; return what is held afterwards."""
        ...


@final
class NoBoard:
    """Nothing has loaded yet: the click opens a placeholder and waits on one.

    The state a session starts in, and the one it returns to for as long as
    ``bd`` cannot be read at all.
    """

    __slots__ = ()

    def opening(self, work: BoardWork) -> BoardRequest:
        """The placeholder — there is nothing better to show yet."""
        return work.placeholder()

    def refreshed(self, work: BoardWork) -> CachedBoard:
        """Load the board the user is waiting on, timing each stage of the wait.

        Every failure becomes something they can see, because a click that
        produces nothing visible is indistinguishable from a broken menu: a
        ``bd`` that would not run renders its own reason, and anything else
        renders a line pointing at the session log, where its traceback is.

        A failed *load* is not held: the next click starts cold rather than
        answering with a red message. A load that succeeded is held whatever
        became of the push behind it, which has not made the query any less paid.
        """
        try:
            with work.stage(_FETCHED):
                issues = work.issues()
            with work.stage(_BUILT):
                board = work.board(issues)
        except BoardUnavailableError as exc:
            self._show(work, work.unavailable(str(exc)))
            return self
        except Exception:
            logger.exception("building the beads board failed")
            self._show(work, work.unavailable(_UNBUILDABLE))
            return self
        self._show(work, board)
        return HeldBoard(board)

    @staticmethod
    def _show(work: BoardWork, request: BoardRequest) -> None:
        """Push what the user has been waiting for, timing the round trip."""
        with work.stage(_PUSHED):
            work.push(request)


@final
class HeldBoard:
    """A board that loaded: the click shows it now and replaces it when it can."""

    _board: BoardRequest
    __slots__ = ("_board",)

    def __new__(cls, board: BoardRequest) -> Self:
        self = super().__new__(cls)
        self._board = board
        return self

    def opening(self, work: BoardWork) -> BoardRequest:
        """The board itself: the click's answer is the real thing, not a stand-in.

        The line reporting the click says so, because an answer that was the
        board reads very differently from one that was "Loading issues…" and the
        figure alone cannot tell them apart.
        """
        work.note(_FROM_CACHE)
        return self._board

    def refreshed(self, work: BoardWork) -> CachedBoard:
        """Replace the board in place, or leave the one on screen where it is.

        The whole load is one figure here rather than three: the user is reading
        a board while it runs and is not waiting on any stage of it.

        A load that fails leaves that board standing and says why in the log. A
        board a few minutes old is worth more than a red message where the board
        was — the user asked to look at their issues, and the ones from the last
        load are still very nearly the answer.
        """
        try:
            with work.stage(_REFRESHED):
                board = work.fresh()
                work.push(board)
        except BoardUnavailableError as exc:
            logger.warning(
                "the board was not refreshed; the one on screen stands: %s", exc
            )
            return self
        except Exception:
            logger.exception("refreshing the board failed; the one on screen stands")
            return self
        return HeldBoard(board)
