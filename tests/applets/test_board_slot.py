"""Which board survives when a click and the warm-up store into one slot.

The two run on different threads and overlap by design: an early click during
warm-up is what the warm-up is for. So the slot is written by two loaders that
know nothing of each other, and every test here asks the same question — after
both have stored, which board is the next click going to answer with?

The answer must not depend on who stored last. A click's load can fail while the
warm-up's board is landing, and a warm-up that began first can finish storing
after a click that read fresher issues. In both cases the slot keeps the board
from the load that began last, and a state holding no board never displaces one
that does.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.board_load import BoardLoad
from punt_lux.applets.board_slot import BoardSlot
from punt_lux.applets.held_board import HeldBoard
from punt_lux.applets.loading_board import LoadingBoard
from punt_lux.applets.no_board import NoBoard
from punt_lux.apps.beads_board import BeadsBoard
from punt_lux.apps.beads_result import BeadsRows

from .board_doubles import GATE_SECONDS, ISSUE, Source

if TYPE_CHECKING:
    from punt_lux.applets.board_cache import CachedBoard
    from punt_lux.applets.board_order import BoardOrder
    from punt_lux.applets.board_work import BoardWork

# Enough writers to interleave on a real machine without making the test slow.
_WRITERS = 16

# How long a writer is given to cross a store that is already under way. A store
# it can cross takes microseconds, so this is generous; a store it cannot cross
# is waiting on a lock and will still be waiting when this elapses.
_CROSSING_SECONDS = 0.05


def _held() -> HeldBoard:
    """A board that loaded, holding the place its load took as a real one does."""
    source = Source(BeadsRows.of([ISSUE]))
    return HeldBoard(BoardLoad(BeadsBoard.for_project("lux"), source).fresh())


@final
class Crossing:
    """A board whose comparison hangs, holding a store open for another writer.

    A store is three steps — read what is held, compare, write the winner — and
    the second writer's board is lost if it lands between them. The gap is there
    at every speed; a comparison that hangs is only how a test lands in it on
    purpose.
    """

    _held: HeldBoard
    _entered: threading.Event
    _resumed: threading.Event
    __slots__ = ("_entered", "_held", "_resumed")

    def __new__(cls, held: HeldBoard) -> Self:
        self = super().__new__(cls)
        self._held = held
        self._entered = threading.Event()
        self._resumed = threading.Event()
        return self

    @property
    def began_at(self) -> BoardOrder:
        return self._held.began_at

    def newer_of(self, held: CachedBoard) -> CachedBoard:
        """Say the store is under way, and hold it there until it is released."""
        self._entered.set()
        self._resumed.wait(timeout=GATE_SECONDS)
        return self._held.newer_of(held)

    def answered(self, work: BoardWork) -> bool:
        return self._held.answered(work)

    def refreshed(self, work: BoardWork) -> CachedBoard:
        return self._held.refreshed(work)

    def shows(self, work: BoardWork) -> None:
        self._held.shows(work)

    def said(self) -> str:
        return self._held.said()

    def entered(self) -> None:
        """Block until this board's store has read the slot and is comparing."""
        assert self._entered.wait(timeout=GATE_SECONDS), "the store never began"

    def resume(self) -> None:
        """Let the held-open store finish and write its winner."""
        self._resumed.set()


def test_a_board_answers_where_there_was_none() -> None:
    slot = BoardSlot()
    held = _held()

    slot.store(held)

    assert slot.held is held


def test_a_state_with_no_board_never_displaces_one_that_has_it() -> None:
    """The click that failed while the warm-up landed: the board must survive.

    This is the reachable case. The first click of a session can arrive before
    the warm-up has finished — the entry is registered before any board has
    loaded — so it reads an empty state, runs its own load, and if that load
    fails it holds nothing to write back. Writing that nothing over the board
    that arrived meanwhile would cost the next click the whole query.
    """
    slot = BoardSlot()
    held = _held()
    slot.store(held)

    slot.store(NoBoard(LoadingBoard()))

    assert slot.held is held


def test_the_board_that_loaded_last_wins_however_late_the_older_one_lands() -> None:
    """Which writer stored last does not decide it; which load began last does.

    A warm-up that began before a click can still be storing after that click has
    finished. The issues it read are the older ones, and arriving late does not
    make them newer.
    """
    slot = BoardSlot()
    older = _held()
    newer = _held()

    slot.store(newer)
    slot.store(older)

    assert slot.held is newer


def test_a_board_that_loaded_later_replaces_the_one_held() -> None:
    """The ordinary case the cache is for: a fresh board takes the stale one's place."""
    slot = BoardSlot()
    older = _held()
    newer = _held()

    slot.store(older)
    slot.store(newer)

    assert slot.held is newer


def test_a_writer_cannot_cross_a_store_already_under_way() -> None:
    """The board a store is about to write must not be lost to one that lands first.

    Reading the slot, comparing, and writing the winner are one step or they are
    a race: a writer that reads the slot before another writes it, and writes
    after, keeps the board it read and drops the one that arrived between. Here
    the second writer is given a store that is already comparing to cross, and it
    does not get through — its board is written after, and it is the one kept.
    """
    slot = BoardSlot()
    crossed = Crossing(_held())
    newer = _held()

    first = threading.Thread(target=slot.store, args=(crossed,))
    first.start()
    crossed.entered()  # the first store has read the slot and not yet written

    second = threading.Thread(target=slot.store, args=(newer,))
    second.start()
    second.join(timeout=_CROSSING_SECONDS)  # it is held out, not let through
    crossed.resume()

    first.join(timeout=GATE_SECONDS)
    second.join(timeout=GATE_SECONDS)
    assert slot.held is newer


def test_the_newest_board_survives_writers_storing_at_once() -> None:
    """Every writer reads, compares and writes; none may lose another's board.

    Two threads is the real case and this is more, because a comparison and a
    write that are not one step drop a board only on the interleaving that lands
    between them. Whatever order these arrive in, the slot ends up holding the
    board from the load that began last.
    """
    slot = BoardSlot()
    boards = [_held() for _ in range(_WRITERS)]
    ready = threading.Barrier(_WRITERS)

    def store(held: HeldBoard) -> None:
        ready.wait(timeout=GATE_SECONDS)
        slot.store(held)

    writers = [threading.Thread(target=store, args=(held,)) for held in boards]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(timeout=GATE_SECONDS)

    assert slot.held is boards[-1]
