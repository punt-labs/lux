"""``BoundedInbox`` -- the bounded per-connection FIFO of undelivered messages.

The bound is the callback hold's backstop applied to the Agent Subscribe inbox:
under capacity the queue is a plain FIFO; at capacity a new message drops and
logs the oldest undelivered one, so the newest is always admitted and an
undrained inbox never grows without end.
"""

from __future__ import annotations

import logging
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
