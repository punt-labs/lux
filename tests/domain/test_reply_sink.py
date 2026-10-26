"""ReplySink -- a reply goes to the request it answers; a stray one is not hidden."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.reply_sink import ReplySink
from punt_lux.domain.hub.reply_waiters import ReplyOutOfOrderError
from punt_lux.domain.hub.settlement import Settlement
from punt_lux.protocol import AckMessage, PongMessage, QueryResponse

if TYPE_CHECKING:
    from punt_lux.domain.hub.connection_closed import RetireCause


def _discard(sink: ReplySink, cause: RetireCause) -> Settlement:
    """End the sink and take its ledger at once, as a retire that reads nothing."""
    sink.end(cause)
    return sink.capture()


class TestAcks:
    def test_an_ack_goes_to_the_oldest_scene_owed(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a")
        sink.owe_ack("b")

        sink.deliver(AckMessage(scene_id="a"))
        assert sink.owed_acks == 1
        sink.deliver(AckMessage(scene_id="b"))

        assert sink.owed_acks == 0

    def test_a_scene_id_that_repeats_is_told_apart_by_position(self) -> None:
        sink = ReplySink()
        sink.owe_ack("x")
        sink.owe_ack("x")

        sink.deliver(AckMessage(scene_id="x", ts=1.0))
        assert sink.owed_acks == 1

        sink.deliver(AckMessage(scene_id="x", ts=2.0))
        assert sink.owed_acks == 0

    def test_an_ack_naming_another_scene_than_the_oldest_owed_is_refused(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a")

        with pytest.raises(ReplyOutOfOrderError, match="'b' arrived where 'a'"):
            sink.deliver(AckMessage(scene_id="b"))

    def test_an_ack_when_none_is_owed_is_a_skewed_stream_not_a_stray(self) -> None:
        sink = ReplySink()

        with pytest.raises(ReplyOutOfOrderError, match="none was owed"):
            sink.deliver(AckMessage(scene_id="stray"))

    def test_the_sink_is_bounded_by_the_scenes_written_not_the_replies_read(
        self,
    ) -> None:
        sink = ReplySink()
        for i in range(1000):
            sink.owe_ack(f"s{i}")
            sink.deliver(AckMessage(scene_id=f"s{i}"))

        assert sink.owed_acks == 0


class TestPongs:
    def test_a_pong_answers_the_ping_whose_ts_it_echoes(self) -> None:
        sink = ReplySink()
        ping = sink.expect_pong(5.0)

        sink.deliver(PongMessage(ts=5.0))

        assert sink.await_reply(ping, 0.0) == PongMessage(ts=5.0)

    def test_a_pong_for_another_ts_is_dropped(self) -> None:
        sink = ReplySink()
        ping = sink.expect_pong(5.0)

        sink.deliver(PongMessage(ts=4.0))

        assert not sink.answered(ping)

    def test_a_repeated_pong_is_dropped(self) -> None:
        sink = ReplySink()
        sink.deliver(PongMessage(ts=1.0))
        ping = sink.expect_pong(1.0)
        sink.deliver(PongMessage(ts=1.0))
        sink.deliver(PongMessage(ts=1.0))

        assert sink.await_reply(ping, 0.0) == PongMessage(ts=1.0)

    def test_a_pong_after_the_ping_was_abandoned_is_dropped(self) -> None:
        sink = ReplySink()
        ping = sink.expect_pong(1.0)
        sink.abandon(ping)

        sink.deliver(PongMessage(ts=1.0))

        assert not sink.answered(ping)

    def test_a_second_ping_while_one_is_in_flight_is_refused(self) -> None:
        sink = ReplySink()
        sink.expect_pong(1.0)

        with pytest.raises(RuntimeError, match="already in flight"):
            sink.expect_pong(2.0)


class TestQueries:
    def test_a_response_answers_the_query_in_flight(self) -> None:
        sink = ReplySink()
        query = sink.expect_query()

        sink.deliver(QueryResponse(method="m"))

        assert sink.await_reply(query, 0.0) == QueryResponse(method="m")

    def test_a_response_with_no_query_in_flight_is_a_skewed_stream(self) -> None:
        sink = ReplySink()

        with pytest.raises(ReplyOutOfOrderError, match="none in flight"):
            sink.deliver(QueryResponse(method="m"))

    def test_a_second_response_is_refused_once_the_first_was_taken(self) -> None:
        sink = ReplySink()
        query = sink.expect_query()
        sink.deliver(QueryResponse(method="m", result={"n": 1}))

        with pytest.raises(ReplyOutOfOrderError):
            sink.deliver(QueryResponse(method="m", result={"n": 2}))

        assert sink.await_reply(query, 0.0) == QueryResponse(
            method="m", result={"n": 1}
        )

    def test_a_second_query_while_one_is_in_flight_is_refused(self) -> None:
        sink = ReplySink()
        sink.expect_query()

        with pytest.raises(RuntimeError, match="already in flight"):
            sink.expect_query()


class TestWaiting:
    def test_a_reply_that_arrives_while_waiting_wakes_the_waiter(self) -> None:
        sink = ReplySink()
        ping = sink.expect_pong(1.0)
        timer = threading.Timer(0.05, lambda: sink.deliver(PongMessage(ts=1.0)))
        timer.start()

        assert sink.await_reply(ping, 3.0) == PongMessage(ts=1.0)
        timer.join()

    def test_no_reply_in_time_is_none(self) -> None:
        sink = ReplySink()

        assert sink.await_reply(sink.expect_pong(1.0), 0.02) is None

    def test_discarding_the_sink_fails_the_waiter_at_once(self) -> None:
        sink = ReplySink()
        ping = sink.expect_pong(1.0)
        timer = threading.Timer(0.05, _discard, args=[sink, "hub"])
        timer.start()

        with pytest.raises(ConnectionClosedError, match="closed while a reply"):
            sink.await_reply(ping, 5.0)
        timer.join()

    def test_a_discarded_sink_takes_no_new_request(self) -> None:
        sink = ReplySink()
        _discard(sink, "hub")

        with pytest.raises(ConnectionClosedError):
            sink.expect_query()
        with pytest.raises(ConnectionClosedError):
            sink.owe_ack("a")

    def test_discarding_drops_what_was_owed(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a")

        _discard(sink, "hub")

        assert sink.owed_acks == 0


class TestTheLedgerIsWhatTheDisplayStillOwed:
    def test_the_discard_hands_back_the_scenes_never_acked_in_write_order(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a")
        sink.owe_ack("b")
        sink.owe_ack("c")
        sink.deliver(AckMessage(scene_id="a"))

        settlement = _discard(sink, "display")

        assert settlement.owed == ("b", "c")
        assert settlement.acked

    def test_a_second_discard_owes_nothing_and_keeps_the_first_cause(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a")
        _discard(sink, "display")

        second = _discard(sink, "hub")

        assert second.owed == ()
        assert second.cause == "display"
        assert sink.ended == "display"

    def test_a_sink_that_never_saw_an_ack_reports_none_applied(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a")

        assert not _discard(sink, "display").acked

    def test_a_live_sink_has_no_end(self) -> None:
        assert ReplySink().ended is None


class TestTheEndHasTwoPhases:
    """The cause is recorded first; the ledger is taken after the reader has read."""

    def test_ending_records_the_first_cause_and_leaves_the_ledger(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a")

        assert sink.end("display")
        assert not sink.end("hub")

        assert sink.ended == "display"
        assert sink.owed_acks == 1
        assert not sink.captured

    def test_an_ack_sent_before_the_end_is_still_applied_until_the_capture(
        self,
    ) -> None:
        sink = ReplySink()
        sink.owe_ack("a")
        sink.owe_ack("b")
        sink.end("display")

        sink.deliver(AckMessage(scene_id="a"))  # read after the end, sent before it
        settlement = sink.capture()

        assert settlement.owed == ("b",)
        assert settlement.acked

    def test_a_pong_after_the_end_is_parked_for_nobody(self) -> None:
        sink = ReplySink()
        ping = sink.expect_pong(1.0)
        sink.end("display")

        sink.deliver(PongMessage(ts=1.0))

        assert not sink.answered(ping)

    def test_nothing_is_delivered_once_the_ledger_is_captured(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a")
        sink.end("display")
        sink.capture()

        sink.deliver(AckMessage(scene_id="a"))  # not a skew: the sink is closed

        assert sink.captured

    def test_an_ended_sink_fails_a_waiter_and_still_owes_a_written_scene(self) -> None:
        sink = ReplySink()
        ping = sink.expect_pong(1.0)
        sink.end("unresponsive")

        sink.owe_ack("a")  # the bytes were on the wire: owed whatever the end state

        assert sink.owed_acks == 1
        with pytest.raises(ConnectionClosedError):
            sink.await_reply(ping, 0.0)

    def test_a_captured_sink_refuses_a_scene_and_records_nothing(self) -> None:
        sink = ReplySink()
        sink.end("display")
        sink.capture()

        with pytest.raises(ConnectionClosedError):
            sink.owe_ack("a")

        assert sink.owed_acks == 0

    def test_capturing_a_sink_that_has_not_ended_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not ended"):
            ReplySink().capture()

    def test_a_second_capture_owes_nothing(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a")
        sink.end("display")
        sink.capture()

        assert sink.capture().owed == ()


class TestAWaitForTheLedgerToEmpty:
    def test_nothing_owed_needs_no_wait(self) -> None:
        assert ReplySink().expect_drained() is None

    def test_the_ack_that_empties_the_ledger_answers_it(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a")
        sink.owe_ack("b")
        wait = sink.expect_drained()
        assert wait is not None

        sink.deliver(AckMessage(scene_id="a"))
        assert not sink.answered(wait)
        sink.deliver(AckMessage(scene_id="b"))

        assert sink.answered(wait)

    def test_an_end_fails_the_wait(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a")
        wait = sink.expect_drained()
        assert wait is not None
        sink.end("hub")

        with pytest.raises(ConnectionClosedError):
            sink.await_reply(wait, 0.0)

    def test_a_second_wait_is_refused(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a")
        assert sink.expect_drained() is not None

        with pytest.raises(RuntimeError, match="already in flight"):
            sink.expect_drained()


class TestARetiredDialNeverDelivers:
    def test_a_reply_delivered_after_the_discard_answers_nobody_and_raises_nothing(
        self,
    ) -> None:
        sink = ReplySink()
        ping = sink.expect_pong(1.0)
        _discard(sink, "hub")

        sink.deliver(PongMessage(ts=1.0))
        sink.deliver(AckMessage(scene_id="stray"))  # not even a skew: it is retired
        sink.deliver(QueryResponse(method="m"))

        assert not sink.answered(ping)

    def test_a_reply_that_arrived_before_the_discard_is_still_taken(self) -> None:
        sink = ReplySink()
        ping = sink.expect_pong(1.0)
        sink.deliver(PongMessage(ts=1.0))

        _discard(sink, "hub")

        assert sink.await_reply(ping, 0.0) == PongMessage(ts=1.0)


class TestTheClosedFlagIsOneHoldWithTheDiscard:
    """A delivery sees the closed flag in the same lock hold it puts in.

    The discard writes the flag under the sink's lock, and ``deliver`` reads it
    under that lock in the same hold as the put: a delivery that is waiting on the
    lock when the dial is retired sees the retirement and puts nothing.
    """

    def test_a_delivery_queued_behind_the_discard_sees_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = ReplySink()
        sink.end("hub")
        outcome: list[BaseException | None] = []
        inside, gate = threading.Event(), threading.Event()
        real = Settlement

        def parked(*args: object) -> Settlement:
            inside.set()  # the capture holds the sink's lock and sits here
            assert gate.wait(5.0)
            return real(*args)  # type: ignore[arg-type]  # the capture's own arguments

        monkeypatch.setattr("punt_lux.domain.hub.reply_sink.Settlement", parked)

        def deliver() -> None:
            try:
                sink.deliver(AckMessage(scene_id="stray"))  # owed nothing
            except ReplyOutOfOrderError as exc:
                outcome.append(exc)
            else:
                outcome.append(None)

        capturing = threading.Thread(target=sink.capture)
        capturing.start()
        assert inside.wait(3.0)
        thread = threading.Thread(target=deliver)
        thread.start()
        thread.join(timeout=0.1)
        assert thread.is_alive(), "the delivery did not wait for the lock"
        gate.set()
        capturing.join(timeout=3.0)
        thread.join(timeout=3.0)

        assert outcome == [None], "the delivery read the flag before the hold"

    def test_a_stray_ack_before_the_discard_is_out_of_order(self) -> None:
        sink = ReplySink()

        with pytest.raises(ReplyOutOfOrderError):
            sink.deliver(AckMessage(scene_id="stray"))
