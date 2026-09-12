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
from collections import deque
from typing import TYPE_CHECKING

from punt_lux.domain.hub import inbox_queue as inbox_queue_module
from punt_lux.domain.hub.inbox_queue import INBOX_CAPACITY, BoundedInbox
from punt_lux.domain.ids import ConnectionId
from punt_lux.protocol.messages.observer import ObserverMessage

if TYPE_CHECKING:
    import pytest

_CONN = ConnectionId("inbox-queue-test")


def _msg(topic: str) -> ObserverMessage:
    return ObserverMessage(topic=topic, payload={})


class _TearOnCheckDeque(deque[ObserverMessage]):
    """A deque that pops once at the instant ``put`` tests its full-check.

    ``put`` reads ``len(queue) >= capacity`` and then, if full, drops the oldest.
    This deque returns the true (full) length for that check but pops one element
    as a side effect first -- deterministically reproducing an unguarded consumer
    dequeuing between put's check and its drop. put then drops against a queue a
    consumer has already made room in: the spurious drop the condition prevents.
    Armed once so only the full-check tears, not the drop's own emptiness probe.
    """

    _capacity: int
    _armed: bool

    def __init__(self, capacity: int) -> None:
        super().__init__()
        self._capacity = capacity
        self._armed = True

    def __len__(self) -> int:
        length = super().__len__()
        if self._armed and length >= self._capacity:
            self._armed = False
            super().popleft()
        return length


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


def _drop_lengths(inbox: BoundedInbox, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Record the deque length observed at each drop's log point.

    A drop pops the oldest, logs, then ``put`` appends -- so at log time a
    genuinely-full drop leaves ``capacity - 1`` queued, while a dequeue that tore
    into the compound leaves fewer. Patching the sole drop-site logger captures
    that length without reaching past the public drop signal.
    """
    observed: list[int] = []

    def record(*_args: object, **_kwargs: object) -> None:
        observed.append(len(inbox._queue))

    monkeypatch.setattr(inbox_queue_module.logger, "warning", record)
    return observed


def test_a_dequeue_between_puts_check_and_drop_causes_a_spurious_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unserialized dequeue makes ``put`` drop against a queue with room.

    ``put``'s admission is compound: check ``len >= capacity``, drop the oldest,
    then append. A *consumer* is a third party on the same deque, so guarding only
    the two producers is not enough (jms's model-check selected exactly this
    witness). This drives the real ``put`` over a deque that pops once at the
    full-check -- the deterministic stand-in for an unguarded ``get`` dequeuing
    between the check and the drop. put still sees "full" and drops, but the queue
    already had room, so the drop is observed at ``capacity - 2``: one message
    spuriously lost. The control -- nothing dequeuing mid-compound, which is what
    the condition guarantees for a real consumer -- leaves ``capacity - 1``.
    """
    capacity = 2

    torn = BoundedInbox(_CONN, capacity=capacity)
    torn._queue = _TearOnCheckDeque(capacity)
    for index in range(capacity):  # start full
        torn._queue.append(_msg(f"seed-{index}"))
    torn_drops = _drop_lengths(torn, monkeypatch)
    torn.put(_msg("newest"))
    # The tear: put dropped with only capacity-2 left -- a message that had room.
    assert torn_drops == [capacity - 2]

    clean = BoundedInbox(_CONN, capacity=capacity)
    for index in range(capacity):  # start full
        clean.put(_msg(f"seed-{index}"))
    clean_drops = _drop_lengths(clean, monkeypatch)
    clean.put(_msg("newest"))
    # No dequeue interleaved: the drop fired at a genuinely full queue.
    assert clean_drops == [capacity - 1]


def test_a_real_guarded_consumer_never_tears_puts_compound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real ``get`` under the condition never lands inside ``put``'s compound.

    The fix routes ``get`` through the same condition as ``put``, so a concurrent
    consumer cannot dequeue between put's full-check and its drop. Under a
    producer and consumer hammering one inbox with the switch interval shrunk to
    force hand-offs, every drop that fires is observed at ``capacity - 1`` -- never
    the ``capacity - 2`` the unserialized dequeue produced above. The assertion
    holds whether or not any drop fired, so it never flakes; the deterministic
    witness above proves the observable is not vacuous.
    """
    capacity = 2
    puts = 4000
    inbox = BoundedInbox(_CONN, capacity=capacity)
    for index in range(capacity):  # start full
        inbox.put(_msg(f"seed-{index}"))
    observed = _drop_lengths(inbox, monkeypatch)

    start = threading.Barrier(2)
    stop = threading.Event()

    def produce() -> None:
        start.wait()
        for index in range(puts):
            inbox.put(_msg(f"m-{index}"))
        stop.set()

    def consume() -> None:
        start.wait()
        while not stop.is_set():
            inbox.get(0.001)

    threads = [threading.Thread(target=produce), threading.Thread(target=consume)]
    previous_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        sys.setswitchinterval(previous_interval)

    # Every drop the guarded consumer coexisted with fired at a full queue.
    assert all(remaining == capacity - 1 for remaining in observed)
