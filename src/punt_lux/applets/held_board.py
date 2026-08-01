"""HeldBoard — a board that loaded, and what the next click does with it.

This is the state the warm-up exists to reach. A click holding one answers with
it immediately and reloads underneath, so the query nobody wants to watch runs
behind something real; and a reload that fails leaves it standing, because a
board a few minutes old is worth more than a red message where the board was.

What it holds is the board a load built, which carries the place that load began
at — and that place is what decides a race between two loading threads. See
:class:`~punt_lux.applets.built_board.BuiltBoard` and
:class:`~punt_lux.applets.board_order.BoardOrder`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.beads_source import BoardUnavailableError

if TYPE_CHECKING:
    from punt_lux.applets.board_cache import CachedBoard
    from punt_lux.applets.board_load import BoardRequest
    from punt_lux.applets.board_order import BoardOrder
    from punt_lux.applets.board_work import BoardWork
    from punt_lux.applets.built_board import BuiltBoard

logger = logging.getLogger(__name__)

__all__ = ["HeldBoard"]

# The load a user is not waiting on, under one figure: they have a board to read
# while it runs, and no stage of it is their problem.
_REFRESHED = "refreshed"

# What the click's line says its answer was, when the answer was the real board.
_FROM_CACHE = "cached board"


@final
class HeldBoard:
    """A board that loaded: the click shows it now and replaces it when it can."""

    _built: BuiltBoard
    __slots__ = ("_built",)

    def __new__(cls, built: BuiltBoard) -> Self:
        self = super().__new__(cls)
        self._built = built
        return self

    @property
    def began_at(self) -> BoardOrder:
        """Where the load that produced this board sits in the order they began."""
        return self._built.began_at

    def newer_of(self, held: CachedBoard) -> CachedBoard:
        """This board, unless *held* holds one whose load began after this one's.

        Neither which writer stored last nor which load returned last decides it.
        A warm-up that began before a click can return and store after it, and
        the issues it read are the older ones however late its board arrives.
        """
        return held if held.began_at.after(self.began_at) else self

    def opening(self, work: BoardWork) -> BoardRequest:
        """The board itself: the click's answer is the real thing, not a stand-in.

        The line reporting the click says so, because an answer that was the
        board reads very differently from one that was "Loading issues…" and the
        figure alone cannot tell them apart.
        """
        work.note(_FROM_CACHE)
        return self._built.request

    def refreshed(self, work: BoardWork) -> CachedBoard:
        """Replace the board in place, or leave the one on screen where it is.

        The whole load is one figure here rather than three: the user is reading
        a board while it runs and is not waiting on any stage of it.

        A load that fails leaves that board standing and says why in the log. A
        board a few minutes old is worth more than a red message where the board
        was — the user asked to look at their issues, and the ones from the last
        load are still very nearly the answer.

        A load that succeeded is held whatever became of the push behind it: a
        Hub that went away between the query and the round trip has not made the
        issues any less read.
        """
        try:
            with work.stage(_REFRESHED):
                built = work.fresh()
                built.push(work)
        except BoardUnavailableError as exc:
            logger.warning(
                "the board was not refreshed; the one on screen stands: %s", exc
            )
            return self
        except Exception:
            logger.exception("refreshing the board failed; the one on screen stands")
            return self
        return HeldBoard(built)
