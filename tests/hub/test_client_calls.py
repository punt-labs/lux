"""ClientCalls — the Hub's table of requests pending on a provider's listen leg.

The rules under test are DES-107 decision 3. A call leaves ``pending`` once (C1);
a reply counts only from the session the request went to (C2); an outcome removes
the entry (C3); a session's end resolves every call on it as lost (C4); a call
reaching its deadline times out (C5); resolution wakes the waiter outside the
table's lock (C6). At most 8 calls are pending per session, and a reply payload
over 256 KiB is a fault.
"""

from __future__ import annotations

import threading

import pytest

from punt_lux.hub.call_outcomes import (
    Lost,
    ProviderBusyError,
    Refused,
    Replied,
    TimedOut,
)
from punt_lux.hub.client_calls import ClientCalls
from punt_lux.wire.model.messages.relay_frames import RefusalFrame, ReplyFrame


def _calls(deadline_s: float = 5.0) -> ClientCalls:
    return ClientCalls(boot="b1", deadline_s=deadline_s)


def test_a_request_frame_carries_a_fresh_id_and_the_request() -> None:
    calls = _calls()
    ticket = calls.open_session()

    first = calls.enter(ticket, "terminal", "ls", {"x": 1})
    second = calls.enter(ticket, "terminal", "ls", {})

    assert first.frame.request_id == "cb1.1"
    assert second.frame.request_id == "cb1.2"
    assert (first.frame.service, first.frame.operation) == ("terminal", "ls")
    assert first.frame.payload == {"x": 1}


def test_a_reply_from_the_session_resolves_the_call() -> None:
    calls = _calls()
    ticket = calls.open_session()
    call = calls.enter(ticket, "terminal", "ls", {})

    assert calls.reply(ticket, ReplyFrame(request_id="cb1.1", payload={"a": 1}))

    assert call.wait() == Replied({"a": 1})


def test_a_refusal_from_the_session_resolves_the_call() -> None:
    calls = _calls()
    ticket = calls.open_session()
    call = calls.enter(ticket, "terminal", "kill", {})

    resolved = calls.refuse(
        ticket, RefusalFrame(request_id="cb1.1", code="not_found", reason="no id")
    )

    assert resolved
    assert call.wait() == Refused("not_found", "no id")


def test_a_reply_from_another_session_is_dropped_and_the_call_stays_pending() -> None:
    calls = _calls(deadline_s=0.05)
    real = calls.open_session()
    forger = calls.open_session()
    call = calls.enter(real, "terminal", "new", {})

    forged = calls.reply(forger, ReplyFrame(request_id="cb1.1", payload={"forged": 1}))

    assert not forged
    assert call.wait() == TimedOut()


def test_a_second_frame_for_a_resolved_call_is_dropped() -> None:
    calls = _calls()
    ticket = calls.open_session()
    call = calls.enter(ticket, "terminal", "ls", {})
    assert calls.reply(ticket, ReplyFrame(request_id="cb1.1", payload={"a": 1}))

    again = calls.reply(ticket, ReplyFrame(request_id="cb1.1", payload={"a": 2}))
    refused = calls.refuse(
        ticket, RefusalFrame(request_id="cb1.1", code="fault", reason="late")
    )

    assert not again
    assert not refused
    assert call.wait() == Replied({"a": 1})


def test_a_frame_for_an_unknown_id_is_dropped() -> None:
    calls = _calls()
    ticket = calls.open_session()

    assert not calls.reply(ticket, ReplyFrame(request_id="cb1.99", payload={}))


def test_a_late_reply_cannot_satisfy_a_later_call() -> None:
    calls = _calls(deadline_s=0.01)
    ticket = calls.open_session()
    first = calls.enter(ticket, "terminal", "ls", {})
    assert first.wait() == TimedOut()
    second = calls.enter(ticket, "terminal", "ls", {})

    late = calls.reply(ticket, ReplyFrame(request_id="cb1.1", payload={"late": 1}))

    assert not late
    assert calls.reply(ticket, ReplyFrame(request_id="cb1.2", payload={"ok": 1}))
    assert second.wait() == Replied({"ok": 1})


def test_a_sessions_end_resolves_every_call_on_it_as_lost() -> None:
    calls = _calls()
    ended = calls.open_session()
    other = calls.open_session()
    first = calls.enter(ended, "terminal", "ls", {})
    second = calls.enter(ended, "terminal", "new", {})
    kept = calls.enter(other, "terminal", "ls", {})

    lost = calls.end_session(ended)

    assert lost == 2
    assert first.wait() == Lost()
    assert second.wait() == Lost()
    assert calls.reply(other, ReplyFrame(request_id="cb1.3", payload={}))
    assert kept.wait() == Replied({})


def test_a_reply_after_the_session_ended_is_dropped() -> None:
    calls = _calls()
    ticket = calls.open_session()
    call = calls.enter(ticket, "terminal", "ls", {})
    calls.end_session(ticket)

    assert not calls.reply(ticket, ReplyFrame(request_id="cb1.1", payload={}))
    assert call.wait() == Lost()


def test_the_ninth_pending_call_on_a_session_is_refused_before_it_is_sent() -> None:
    calls = _calls()
    ticket = calls.open_session()
    for _ in range(8):
        calls.enter(ticket, "terminal", "ls", {})

    with pytest.raises(ProviderBusyError, match="busy"):
        calls.enter(ticket, "terminal", "ls", {})


def test_a_resolved_call_frees_its_slot() -> None:
    calls = _calls()
    ticket = calls.open_session()
    for _ in range(8):
        calls.enter(ticket, "terminal", "ls", {})
    assert calls.reply(ticket, ReplyFrame(request_id="cb1.1", payload={}))

    calls.enter(ticket, "terminal", "ls", {})


def test_a_reply_over_the_size_cap_is_a_fault() -> None:
    calls = _calls()
    ticket = calls.open_session()
    call = calls.enter(ticket, "terminal", "ls", {})
    huge: dict[str, object] = {"blob": "x" * (256 * 1024 + 1)}

    assert calls.reply(ticket, ReplyFrame(request_id="cb1.1", payload=huge))

    outcome = call.wait()
    assert isinstance(outcome, Refused)
    assert outcome.code == "fault"


def test_a_waiter_blocked_in_wait_wakes_when_the_reply_arrives() -> None:
    calls = _calls()
    ticket = calls.open_session()
    call = calls.enter(ticket, "terminal", "ls", {})
    outcomes: list[object] = []
    waiter = threading.Thread(target=lambda: outcomes.append(call.wait()))
    waiter.start()

    assert calls.reply(ticket, ReplyFrame(request_id="cb1.1", payload={"a": 1}))
    waiter.join(timeout=5)

    assert not waiter.is_alive()
    assert outcomes == [Replied({"a": 1})]


def test_a_waiter_blocked_in_wait_wakes_when_its_session_ends() -> None:
    calls = _calls()
    ticket = calls.open_session()
    call = calls.enter(ticket, "terminal", "ls", {})
    outcomes: list[object] = []
    waiter = threading.Thread(target=lambda: outcomes.append(call.wait()))
    waiter.start()

    calls.end_session(ticket)
    waiter.join(timeout=5)

    assert outcomes == [Lost()]


def test_waiting_twice_reports_the_one_outcome() -> None:
    calls = _calls()
    ticket = calls.open_session()
    call = calls.enter(ticket, "terminal", "ls", {})
    calls.reply(ticket, ReplyFrame(request_id="cb1.1", payload={"a": 1}))

    assert call.wait() == call.wait() == Replied({"a": 1})
