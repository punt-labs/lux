"""CallEntry and SessionTicket — one pending call, and the session it went to."""

from __future__ import annotations

import time

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


def test_waiting_ends_at_the_deadline_measured_from_construction() -> None:
    entry = CallEntry(SessionTicket(1), 0.05)
    time.sleep(0.1)

    started = time.monotonic()
    entry.wait_until_deadline()

    assert time.monotonic() - started < 0.04


def test_waking_releases_a_waiter_before_the_deadline() -> None:
    entry = CallEntry(SessionTicket(1), 30.0)
    entry.wake()

    started = time.monotonic()
    entry.wait_until_deadline()

    assert time.monotonic() - started < 1.0


def test_a_ticket_ends_once_and_stays_ended() -> None:
    ticket = SessionTicket(1)
    assert not ticket.ended

    ticket.end()

    assert ticket.ended
