"""CallEntry and SessionTicket — one pending call, and the session it went to."""

from __future__ import annotations

import threading
from typing import Self

from punt_lux.hub.call_entry import CallEntry, SessionTicket
from punt_lux.hub.call_outcomes import Replied


def test_an_entry_is_pending_until_concluded() -> None:
    entry = CallEntry(SessionTicket(1), 5.0)

    assert entry.outcome is None
    entry.conclude(Replied({"a": 1}))

    assert entry.outcome == Replied({"a": 1})


def test_an_entry_knows_only_the_session_it_was_sent_to() -> None:
    sent_to, other = SessionTicket(1), SessionTicket(1)
    entry = CallEntry(sent_to, 5.0)

    assert entry.was_sent_to(sent_to)
    assert not entry.was_sent_to(other)


class _FakeClock:
    """A clock the test advances, so a deadline passes without waiting for it."""

    _now: float
    __slots__ = ("_now",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._now = 0.0
        return self

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _waited(entry: CallEntry) -> bool:
    """Whether ``wait_until_deadline`` returns; a hang guard, not a duration."""
    waiter = threading.Thread(target=entry.wait_until_deadline, daemon=True)
    waiter.start()
    waiter.join(timeout=10)
    return not waiter.is_alive()


def test_the_deadline_is_measured_from_construction() -> None:
    clock = _FakeClock()
    entry = CallEntry(SessionTicket(1), 5.0, clock)
    assert not entry.expired

    clock.advance(4.9)
    assert not entry.expired

    clock.advance(0.2)
    assert entry.expired


def test_waiting_after_the_deadline_returns_at_once() -> None:
    clock = _FakeClock()
    entry = CallEntry(SessionTicket(1), 3600.0, clock)
    clock.advance(3601.0)

    assert _waited(entry)


def test_waking_releases_a_waiter_before_the_deadline() -> None:
    entry = CallEntry(SessionTicket(1), 3600.0)
    entry.wake()

    assert _waited(entry)


def test_a_ticket_ends_once_and_stays_ended() -> None:
    ticket = SessionTicket(1)
    assert not ticket.ended

    ticket.end()

    assert ticket.ended
