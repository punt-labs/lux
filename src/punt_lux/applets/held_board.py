"""HeldBoard — a board that loaded, and what the next click does with it.

This is the state the warm-up exists to reach. A click holding one answers with
it immediately and reloads underneath, so the query nobody wants to watch runs
behind something real; and a reload that fails leaves it standing, because a
board a few minutes old is worth more than a red message where the board was.

Each one records where it sits in the order boards loaded, which is what decides
a race between two loading threads: see
:class:`~punt_lux.applets.board_cache.CachedBoard`.
"""

from __future__ import annotations

import logging
from itertools import count
from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.beads_source import BoardUnavailableError

if TYPE_CHECKING:
    from punt_lux.applets.board_cache import CachedBoard
    from punt_lux.applets.board_load import BoardRequest
    from punt_lux.applets.board_work import BoardWork

logger = logging.getLogger(__name__)

__all__ = ["HeldBoard"]

# The load a user is not waiting on, under one figure: they have a board to read
# while it runs, and no stage of it is their problem.
_REFRESHED = "refreshed"

# What the click's line says its answer was, when the answer was the real board.
_FROM_CACHE = "cached board"

# The order boards finished loading in. A counter rather than a clock, because
# all the rule needs is which of two boards loaded later, and a counter answers
# that at every clock resolution — including two loads that finished inside the
# same tick of one.
_LOADS = count()


@final
class HeldBoard:
    """A board that loaded: the click shows it now and replaces it when it can."""

    _board: BoardRequest
    _loaded_at: int
    __slots__ = ("_board", "_loaded_at")

    def __new__(cls, board: BoardRequest) -> Self:
        self = super().__new__(cls)
        self._board = board
        # Taken here because here is where a board has just finished loading:
        # every one of these is built from a load that has this moment returned.
        self._loaded_at = next(_LOADS)
        return self

    @property
    def loaded_at(self) -> int:
        """Where this board sits in the order boards loaded in."""
        return self._loaded_at

    def newer_of(self, held: CachedBoard) -> CachedBoard:
        """This board, unless *held* holds one that loaded after it.

        Which writer stored last does not decide it. A warm-up that began before
        a click can finish storing after it, and the board it read is the older
        one however late it arrives.
        """
        return held if held.loaded_at > self._loaded_at else self

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
