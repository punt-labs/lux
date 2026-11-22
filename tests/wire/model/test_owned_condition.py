"""OwnedCondition knows which thread holds it, across a wait as across a plain hold."""

from __future__ import annotations

import threading

import pytest

from punt_lux.domain.hub.lock_discipline_error import LockDisciplineError
from punt_lux.domain.hub.owned_condition import OwnedCondition


def test_it_is_held_here_exactly_while_inside() -> None:
    cond = OwnedCondition()
    assert not cond.held_here()

    with cond:
        assert cond.held_here()
    assert not cond.held_here()


def test_a_hold_by_another_thread_is_not_a_hold_here() -> None:
    cond = OwnedCondition()
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with cond:
            held.set()
            release.wait(3.0)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert held.wait(3.0)

    assert not cond.held_here()
    release.set()
    holder.join(3.0)


def test_a_wait_gives_the_lock_up_and_the_hold_is_ours_again_after() -> None:
    cond = OwnedCondition()
    seen_during: list[bool] = []

    def other() -> None:
        with cond:
            seen_during.append(cond.held_here())  # taken while the waiter waits
            cond.notify_all()

    with cond:
        thread = threading.Thread(target=other, daemon=True)
        thread.start()
        woke = cond.wait_for(lambda: bool(seen_during), 3.0)
        assert (woke, cond.held_here()) == (True, True)
    thread.join(3.0)

    assert seen_during == [True]


def test_notifying_without_the_hold_raises() -> None:
    with pytest.raises(LockDisciplineError, match="notify"):
        OwnedCondition().notify_all()


def test_waiting_without_the_hold_raises() -> None:
    with pytest.raises(LockDisciplineError, match="wait"):
        OwnedCondition().wait_for(lambda: True, 0.0)
