"""A reconcile applies the list as the authority, then the events buffered after it."""

from __future__ import annotations

from punt_lux.pty.sync_plan import SyncPlan
from punt_lux.wire.stream.session_events import SessionEvent


def _opened(plan: SyncPlan) -> dict[str, str]:
    return {s.session: s.label for s in plan.opened}


def test_a_window_is_opened_for_every_running_session_lacking_one() -> None:
    plan = SyncPlan.reconcile({"t0.1": "a", "t0.2": "b"}, (), frozenset({"t0.1"}))
    assert _opened(plan) == {"t0.2": "b"}


def test_the_window_of_a_session_no_longer_running_is_closed() -> None:
    plan = SyncPlan.reconcile({"t0.2": "b"}, (), frozenset({"t0.1", "t0.2"}))
    assert plan.closed == ("t0.1",)


def test_lost_events_then_a_sync_leave_exactly_the_daemons_sessions() -> None:
    running = {"t0.3": "c"}
    shown = frozenset({"t0.1", "t0.2"})  # both ended while the helper was blind
    plan = SyncPlan.reconcile(running, (), shown)
    assert (_opened(plan), plan.closed) == ({"t0.3": "c"}, ("t0.1", "t0.2"))


def test_an_exit_wins_over_a_creation_of_the_same_id() -> None:
    events = [SessionEvent("created", "t0.4", "d"), SessionEvent("ended", "t0.4", "d")]
    assert SyncPlan.reconcile({}, events, frozenset()).opened == ()


def test_an_exit_wins_even_when_it_precedes_the_creation_in_the_buffer() -> None:
    events = [SessionEvent("ended", "t0.4", "d"), SessionEvent("created", "t0.4", "d")]
    assert SyncPlan.reconcile({}, events, frozenset()).opened == ()


def test_a_buffered_exit_removes_a_session_the_list_still_names() -> None:
    plan = SyncPlan.reconcile(
        {"t0.1": "a"}, [SessionEvent("ended", "t0.1", "a")], frozenset({"t0.1"})
    )
    assert plan.closed == ("t0.1",)


def test_a_buffered_creation_the_list_missed_is_opened() -> None:
    plan = SyncPlan.reconcile({}, [SessionEvent("created", "t0.5", "e")], frozenset())
    assert _opened(plan) == {"t0.5": "e"}
