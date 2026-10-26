"""ReplyWaiters -- the ping and query in flight, on the one lock its sink lends it."""

from __future__ import annotations

import threading

import pytest

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.dial_end import DialEnd
from punt_lux.domain.hub.reply_sink import ReplySink
from punt_lux.domain.hub.reply_waiters import ReplyOutOfOrderError, ReplyWaiters
from punt_lux.protocol import PongMessage, QueryResponse


def _waiters() -> tuple[ReplyWaiters, DialEnd, threading.Condition]:
    cond = threading.Condition()
    end = DialEnd()
    return ReplyWaiters(cond, end), end, cond


def _response() -> QueryResponse:
    return QueryResponse(method="m")


class TestThePing:
    def test_a_pong_echoing_the_ping_answers_it(self) -> None:
        waiters, _, _ = _waiters()
        ping = waiters.expect_pong(1.5)

        waiters.deliver_pong(PongMessage(ts=1.5))

        assert waiters.await_reply(ping, 0.0) == PongMessage(ts=1.5)

    def test_a_pong_for_another_ts_is_dropped(self) -> None:
        waiters, _, _ = _waiters()
        ping = waiters.expect_pong(1.5)

        waiters.deliver_pong(PongMessage(ts=9.0))

        assert waiters.await_reply(ping, 0.0) is None

    def test_a_second_ping_in_flight_is_refused(self) -> None:
        waiters, _, _ = _waiters()
        waiters.expect_pong(1.0)

        with pytest.raises(RuntimeError, match="a ping is already in flight"):
            waiters.expect_pong(2.0)


class TestTheQuery:
    def test_the_next_response_answers_the_query(self) -> None:
        waiters, _, _ = _waiters()
        query = waiters.expect_query()

        waiters.deliver_query(_response())

        assert waiters.await_reply(query, 0.0) == _response()

    def test_a_response_with_no_query_in_flight_is_a_skewed_stream(self) -> None:
        waiters, _, _ = _waiters()

        with pytest.raises(ReplyOutOfOrderError, match="none in flight"):
            waiters.deliver_query(_response())

    def test_a_second_query_in_flight_is_refused(self) -> None:
        waiters, _, _ = _waiters()
        waiters.expect_query()

        with pytest.raises(RuntimeError, match="a query is already in flight"):
            waiters.expect_query()

    def test_an_abandoned_query_keeps_no_late_answer(self) -> None:
        waiters, _, _ = _waiters()
        query = waiters.expect_query()
        waiters.abandon(query)

        with pytest.raises(ReplyOutOfOrderError):
            waiters.deliver_query(_response())

    def test_an_answered_ticket_is_reported_until_it_is_taken(self) -> None:
        waiters, _, _ = _waiters()
        query = waiters.expect_query()
        waiters.deliver_query(_response())

        assert waiters.answered(query) is True
        waiters.await_reply(query, 0.0)
        assert waiters.answered(query) is False


class TestTheEnd:
    def test_a_wait_on_an_ending_dial_is_refused(self) -> None:
        waiters, end, _ = _waiters()
        end.ask_hub()

        with pytest.raises(ConnectionClosedError):
            waiters.expect_query()

    def test_a_waiting_caller_is_failed_the_moment_the_waiters_fail(self) -> None:
        waiters, end, _ = _waiters()
        query = waiters.expect_query()
        outcome: list[BaseException] = []

        def wait() -> None:
            try:
                waiters.await_reply(query, 5.0)
            except ConnectionClosedError as exc:
                outcome.append(exc)

        thread = threading.Thread(target=wait)
        thread.start()
        end.ask_hub()
        waiters.fail_all()
        thread.join(2.0)

        assert len(outcome) == 1


class TestTheOneLock:
    """A Hub request or an end fails a pending ping and query under the sink's lock."""

    def test_the_waiters_use_the_lock_they_were_given(self) -> None:
        waiters, _, cond = _waiters()
        holder_has_it = threading.Event()
        release = threading.Event()
        refused = threading.Event()

        def hold() -> None:
            with cond:
                holder_has_it.set()
                release.wait(2.0)

        thread = threading.Thread(target=hold)
        thread.start()
        holder_has_it.wait(2.0)

        def expect() -> None:
            waiters.expect_query()
            refused.set()

        probe = threading.Thread(target=expect)
        probe.start()
        probe.join(0.2)
        blocked = probe.is_alive()
        release.set()
        thread.join(2.0)
        probe.join(2.0)

        assert blocked, "expect_query took a lock of its own, not the sink's"

    @pytest.mark.parametrize("how", ["request_hub", "end"])
    @pytest.mark.parametrize("what", ["query", "ping"])
    def test_an_end_wakes_a_blocked_waiter_with_a_failure(
        self, how: str, what: str
    ) -> None:
        sink = ReplySink()
        pending = sink.expect_query() if what == "query" else sink.expect_pong(1.0)
        outcome: list[BaseException] = []

        def wait() -> None:
            try:
                sink.await_reply(pending, 10.0)
            except ConnectionClosedError as exc:
                outcome.append(exc)

        thread = threading.Thread(target=wait)
        thread.start()
        sink.request_hub() if how == "request_hub" else sink.end("display")
        thread.join(2.0)

        assert not thread.is_alive(), "the waiter slept through the end"
        assert len(outcome) == 1


class TestFailingAll:
    def test_no_ping_or_query_is_left_in_flight(self) -> None:
        waiters, _, _ = _waiters()
        ping = waiters.expect_pong(1.0)
        waiters.expect_query()

        waiters.fail_all()

        with pytest.raises(ReplyOutOfOrderError):
            waiters.deliver_query(_response())
        waiters.deliver_pong(PongMessage(ts=1.0))
        assert waiters.answered(ping) is False
