"""Retry deadlines retain backoff until success or reset."""

from __future__ import annotations

import pytest

from punt_lux.display.terminal.remote import RemoteSession
from punt_lux.display.terminal.retry_schedule import RetrySchedule


@pytest.fixture
def session() -> RemoteSession:
    return RemoteSession("shell", "", lambda _frame: None)


def test_failures_back_off_to_cap_and_due_consumes_once(session: RemoteSession) -> None:
    schedule = RetrySchedule()
    now = 100.0
    for delay in (0.25, 0.5, 1.0, 2.0, 4.0, 4.0, 4.0):
        schedule.failed(session, now)
        assert schedule.due(now + delay - 0.001) == ()
        now += delay
        assert schedule.due(now) == (session,)
        assert schedule.due(now) == ()


def test_success_resets_delay_and_unknown_success_is_harmless(
    session: RemoteSession,
) -> None:
    schedule = RetrySchedule()
    schedule.succeeded(session)
    schedule.failed(session, 0.0)
    assert schedule.due(0.25) == (session,)
    schedule.succeeded(session)
    schedule.failed(session, 1.0)
    assert schedule.due(1.25) == (session,)


def test_clear_removes_deadlines_and_backoff(session: RemoteSession) -> None:
    schedule = RetrySchedule()
    assert schedule.due(0.0) == ()
    schedule.clear()
    schedule.failed(session, 0.0)
    schedule.clear()
    assert schedule.due(100.0) == ()
    schedule.failed(session, 100.0)
    assert schedule.due(100.25) == (session,)


def test_sessions_have_independent_deadlines_and_repeated_failure_replaces_deadline(
    session: RemoteSession,
) -> None:
    other = RemoteSession("other", "", lambda _frame: None)
    schedule = RetrySchedule()
    schedule.failed(session, 0.0)
    schedule.failed(other, 0.0)
    schedule.failed(session, 0.1)
    assert schedule.due(0.25) == (other,)
    assert schedule.due(0.599) == ()
    assert schedule.due(0.6) == (session,)
