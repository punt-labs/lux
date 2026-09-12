"""``BoundedInbox`` -- the bounded per-connection FIFO of undelivered messages.

The bound is the callback hold's backstop applied to the Agent Subscribe inbox:
under capacity the queue is a plain FIFO; at capacity a new message drops and
logs the oldest undelivered one, so the newest is always admitted and an
undrained inbox never grows without end.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import TYPE_CHECKING

from punt_lux.domain.hub.inbox_queue import INBOX_CAPACITY, BoundedInbox
from punt_lux.domain.ids import ConnectionId
from punt_lux.protocol.messages.observer import ObserverMessage

if TYPE_CHECKING:
    import pytest

_CONN = ConnectionId("inbox-queue-test")


def _msg(topic: str) -> ObserverMessage:
    return ObserverMessage(topic=topic, payload={})


def test_under_capacity_is_a_plain_fifo() -> None:
    inbox = BoundedInbox(_CONN, capacity=5)
    for topic in ("a", "b", "c"):
        inbox.put(_msg(topic))

    assert inbox.depth() == 3
    assert [m.topic for m in inbox.drain()] == ["a", "b", "c"]
    assert inbox.depth() == 0


def test_at_capacity_drops_the_oldest_and_keeps_the_newest() -> None:
    inbox = BoundedInbox(_CONN, capacity=2)
    inbox.put(_msg("a"))
    inbox.put(_msg("b"))
    inbox.put(_msg("c"))  # full at 2: "a" (oldest) is dropped, "c" admitted

    assert inbox.depth() == 2
    assert [m.topic for m in inbox.drain()] == ["b", "c"]


def test_a_full_inbox_warns_when_it_drops(caplog: pytest.LogCaptureFixture) -> None:
    inbox = BoundedInbox(_CONN, capacity=1)
    inbox.put(_msg("first"))

    with caplog.at_level(logging.WARNING, logger="punt_lux.domain.hub.inbox_queue"):
        inbox.put(_msg("second"))

    assert any(
        record.levelno == logging.WARNING and "dropping" in record.getMessage()
        for record in caplog.records
    )
    assert [m.topic for m in inbox.drain()] == ["second"]


def test_get_returns_the_next_message_then_times_out() -> None:
    inbox = BoundedInbox(_CONN, capacity=3)
    inbox.put(_msg("only"))

    received = inbox.get(timeout=1.0)
    assert received is not None
    assert received.topic == "only"
    assert inbox.get(timeout=0.0) is None  # empty -> timeout -> None


def test_default_capacity_is_the_shared_backstop() -> None:
    inbox = BoundedInbox(_CONN)
    for index in range(INBOX_CAPACITY + 5):
        inbox.put(_msg(f"m{index}"))

    # The queue never exceeds the backstop, and the survivors are the newest.
    assert inbox.depth() == INBOX_CAPACITY
    topics = [m.topic for m in inbox.drain()]
    assert topics[0] == "m5"
    assert topics[-1] == f"m{INBOX_CAPACITY + 4}"


def test_two_producers_at_capacity_keep_the_bound_exact() -> None:
    """Two producers hammering one full inbox never overshoot the bound.

    The inbox has two unsynchronized producers -- the ``Hub.publish`` writer
    closure and ``offer`` -- and its admission is a compound check-then-act
    (``qsize`` -> ``_drop_oldest`` -> ``put``). Without the inbox's own lock the
    two race: one pops before the other's ``qsize`` read, so the second sees a
    stale sub-capacity size, skips its drop, and both ``put`` -- overshooting the
    cap. Because every ``put`` here starts from a full queue, each must drop
    exactly one, so ``final == capacity`` iff drops equalled puts; a single
    skipped drop leaves the deficit permanently (later puts drop at most one each
    and never catch up), so ``final > capacity``. This asserts the leaf lock makes
    the bound EXACT: the queue is at ``capacity`` at the end, and no producer ever
    observed it above ``capacity``.
    """
    capacity = 4
    inbox = BoundedInbox(_CONN, capacity=capacity)
    for index in range(capacity):  # start full so every put is an at-capacity drop
        inbox.put(_msg(f"seed-{index}"))

    puts_per_producer = 3000
    start = threading.Barrier(2)
    max_observed: list[int] = []

    def hammer(tag: str) -> None:
        local_max = 0
        start.wait()
        for index in range(puts_per_producer):
            inbox.put(_msg(f"{tag}-{index}"))
            local_max = max(local_max, inbox.depth())
        max_observed.append(local_max)

    # CPython's default 5ms thread-switch interval lets each producer run whole
    # ``put`` calls uninterrupted, so a hand-off almost never lands in the narrow
    # window between the ``qsize`` check and the ``put``. Shrink the interval so
    # the GIL hands off constantly and the race is reliably exercised -- this is
    # what makes the test FAIL if the leaf lock is ever removed (verified: without
    # the lock the queue overshoots to capacity+1), and it stays deterministic
    # WITH the lock, which serializes the compound act regardless of hand-offs.
    previous_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        producers = [
            threading.Thread(target=hammer, args=(tag,)) for tag in ("writer", "offer")
        ]
        for producer in producers:
            producer.start()
        for producer in producers:
            producer.join()
    finally:
        sys.setswitchinterval(previous_interval)

    # Exact bound: no producer ever saw the queue above capacity...
    assert max(max_observed) == capacity
    # ...and it settled at exactly capacity -- drops equalled puts, one per
    # admission, never zero (overshoot) and never two (structurally impossible).
    assert inbox.depth() == capacity
