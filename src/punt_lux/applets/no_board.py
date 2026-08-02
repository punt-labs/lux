"""NoBoard — nothing has loaded, so the click opens a placeholder and waits.

The state a session starts in, and the one it returns to while ``bd`` cannot be
read at all. A click from here is the cold one the warm-up exists to prevent: the
user watches "Loading issues…" for however long the query takes, and every way it
can fail becomes something they see, or the menu simply looks broken.

It holds no board, so it never displaces one — see
:class:`~punt_lux.applets.board_order.BoardOrder` for the order that decides.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from punt_lux.applets.beads_source import BoardUnavailableError
from punt_lux.applets.board_order import BoardOrder
from punt_lux.applets.board_run import BoardRun
from punt_lux.applets.held_board import HeldBoard

if TYPE_CHECKING:
    from punt_lux.applets.board_cache import CachedBoard
    from punt_lux.applets.board_load import BoardRequest
    from punt_lux.applets.board_work import BoardWork

__all__ = ["NoBoard"]

# The round trip that puts a board on screen, watched through a placeholder. The
# waits before it are named in :mod:`punt_lux.applets.board_run`, which times them.
_PUSHED = "pushed"

# What the line says the answer was, for the two a state holding no board can
# give: it put the placeholder up, or it left a frame already up alone. Both are
# fast, so only the line tells them apart.
_PLACEHOLDER = "loading placeholder"
_RAISED = "frame already up"


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

    def answer(self, work: BoardWork) -> None:
        """Raise the frame, and open the placeholder only if there was none up.

        Holding no board, this state has nothing to put in a frame that already
        has one. Whatever is in it — from an earlier run of this applet, or from
        ``lux show beads`` — beats the word "Loading", and a raise that could not
        be answered collapses the same way: the board may well be up, and
        blanking a good one on a failed round trip is the worse mistake. A frame
        that is not up leaves the placeholder as the only thing to show.
        """
        if work.showing():
            work.note(_RAISED)
            return
        work.note(_PLACEHOLDER)
        work.push(work.placeholder())

    def refreshed(self, work: BoardWork) -> CachedBoard:
        """Load the board the user is waiting on, timing each stage of the wait.

        Every failure becomes something they can see, which is why the run hands
        back one reason however it failed. A failed *load* is not held: the next
        click starts cold rather than answering with a red message. A load that
        succeeded is held whatever became of the push behind it, which has not
        made the query any less paid.
        """
        try:
            built = BoardRun(work).staged()
        except BoardUnavailableError as exc:
            self._show_reason(work, work.unavailable(str(exc)))
            return self
        with work.stage(_PUSHED):
            built.push(work)
        return HeldBoard(built)

    @staticmethod
    def _show_reason(work: BoardWork, request: BoardRequest) -> None:
        """Put the red message where the user was waiting, timing the round trip."""
        with work.stage(_PUSHED):
            work.push(request)
