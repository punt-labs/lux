"""NoBoard — nothing has loaded, so the click opens a placeholder and waits.

The state a session starts in, and the one it returns to for as long as ``bd``
cannot be read at all. A click from here is the cold one the warm-up exists to
prevent: the user watches "Loading issues…" for however long the query takes, and
every way it can fail becomes something they can see, because a click that
produces nothing visible is indistinguishable from a broken menu.

It holds no board, so it never displaces one — see
:class:`~punt_lux.applets.board_order.BoardOrder` for the order that decides.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, final

from punt_lux.applets.beads_source import BoardUnavailableError
from punt_lux.applets.board_order import BoardOrder
from punt_lux.applets.held_board import HeldBoard

if TYPE_CHECKING:
    from punt_lux.applets.board_cache import CachedBoard
    from punt_lux.applets.board_load import BoardRequest
    from punt_lux.applets.board_work import BoardWork

logger = logging.getLogger(__name__)

__all__ = ["NoBoard"]

# The stages of a load the user is waiting through, named for what they are
# waiting on: the query to the hosted database, the board built from what it
# returned, and the round trip that puts that board on screen.
_FETCHED = "fetched"
_BUILT = "built"
_PUSHED = "pushed"

# What a click shows when the board could not be built for a reason nobody
# modelled: the reason itself is a traceback, which belongs in the log.
_UNBUILDABLE = "the beads board could not be built — see the session log"


@final
class NoBoard:
    """Nothing has loaded yet: the click opens a placeholder and waits on one."""

    __slots__ = ()

    @property
    def began_at(self) -> BoardOrder:
        """Before every load: this is the state there was before any began."""
        return BoardOrder.before_any_load()

    def newer_of(self, held: CachedBoard) -> CachedBoard:
        """Whatever is already held — a state with no board displaces nothing.

        A click whose ``bd`` failed ends here, and it must not cost the applet a
        board that arrived while it was failing: the warm-up may have finished
        between this click reading the state and writing its result back.
        """
        return held

    def opening(self, work: BoardWork) -> BoardRequest:
        """The placeholder — there is nothing better to show yet."""
        return work.placeholder()

    def refreshed(self, work: BoardWork) -> CachedBoard:
        """Load the board the user is waiting on, timing each stage of the wait.

        Every failure becomes something they can see: a ``bd`` that would not run
        renders its own reason, and anything else renders a line pointing at the
        session log, where its traceback is.

        A failed *load* is not held: the next click starts cold rather than
        answering with a red message. A load that succeeded is held whatever
        became of the push behind it, which has not made the query any less paid.
        """
        try:
            with work.stage(_FETCHED):
                read = work.issues()
            with work.stage(_BUILT):
                built = work.board(read)
        except BoardUnavailableError as exc:
            self._show_reason(work, work.unavailable(str(exc)))
            return self
        except Exception:
            logger.exception("building the beads board failed")
            self._show_reason(work, work.unavailable(_UNBUILDABLE))
            return self
        with work.stage(_PUSHED):
            built.push(work)
        return HeldBoard(built)

    @staticmethod
    def _show_reason(work: BoardWork, request: BoardRequest) -> None:
        """Put the red message where the user was waiting, timing the round trip."""
        with work.stage(_PUSHED):
            work.push(request)
