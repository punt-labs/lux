"""The order two overlapping loads are compared in, and where it is taken.

One rule decides which of two boards an applet keeps, and this is it. The tests
below pin the three things it promises: a place is taken when a load begins, no
two loads share one, and a state holding no board is behind them all.

The threaded case is here rather than left to the service tests because the two
loaders take their places without a lock between them. If taking one were more
than a single step, two loads could come away with the same place and the
comparison between them would have no answer.
"""

from __future__ import annotations

import threading

from punt_lux.applets.board_order import BoardOrder

# Enough takers to interleave on a real machine without making the test slow.
_TAKERS = 32

# How long a taker is given to reach the barrier before the test gives up on it.
_GATE_SECONDS = 5.0


def test_a_load_that_begins_later_takes_a_place_after_one_that_began_first() -> None:
    first = BoardOrder.beginning()
    second = BoardOrder.beginning()

    assert second.after(first)
    assert not first.after(second)


def test_a_place_is_not_after_itself() -> None:
    """The comparison is strict, so a board never displaces its own copy."""
    place = BoardOrder.beginning()

    assert not place.after(place)


def test_a_state_holding_no_board_is_behind_every_load() -> None:
    """Nothing sits before the first load, so nothing it holds displaces a board."""
    nothing = BoardOrder.before_any_load()

    assert BoardOrder.beginning().after(nothing)
    assert not nothing.after(BoardOrder.beginning())


def test_no_two_loads_beginning_at_once_come_away_with_the_same_place() -> None:
    """Two loading threads begin without a lock, so taking a place is one step.

    Sharing a place would leave the comparison with no answer: neither board is
    after the other, so whichever stored last would silently win — which is the
    outcome the order exists to prevent.
    """
    ready = threading.Barrier(_TAKERS)
    taken: list[BoardOrder] = []
    guard = threading.Lock()

    def begin() -> None:
        ready.wait(timeout=_GATE_SECONDS)
        place = BoardOrder.beginning()
        with guard:
            taken.append(place)

    takers = [threading.Thread(target=begin) for _ in range(_TAKERS)]
    for taker in takers:
        taker.start()
    for taker in takers:
        taker.join(timeout=_GATE_SECONDS)

    assert len(taken) == _TAKERS
    # Every pair is ordered one way or the other; none is a tie.
    assert all(
        one.after(other) or other.after(one)
        for index, one in enumerate(taken)
        for other in taken[index + 1 :]
    )
