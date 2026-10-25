"""ReplySink -- a reply goes to the request it answers; a stray one is not hidden."""

from __future__ import annotations

import threading

import pytest

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.reply_sink import ReplyOutOfOrderError, ReplySink
from punt_lux.protocol import AckMessage, PongMessage, QueryResponse


class TestAcks:
    def test_an_ack_goes_to_the_oldest_scene_owed(self) -> None:
        sink = ReplySink()
        first = sink.owe_ack("a", awaited=True)
        second = sink.owe_ack("b", awaited=True)

        sink.deliver(AckMessage(scene_id="a"))
        sink.deliver(AckMessage(scene_id="b"))

        assert (sink.await_reply(first, 0.0), sink.await_reply(second, 0.0)) == (
            AckMessage(scene_id="a"),
            AckMessage(scene_id="b"),
        )

    def test_the_ack_of_a_scene_nobody_waits_for_is_popped_and_dropped(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a", awaited=False)
        waited = sink.owe_ack("b", awaited=True)

        sink.deliver(AckMessage(scene_id="a"))
        assert not sink.answered(waited)
        sink.deliver(AckMessage(scene_id="b"))

        assert sink.await_reply(waited, 0.0) == AckMessage(scene_id="b")
        assert sink.owed_acks == 0

    def test_a_scene_id_that_repeats_is_told_apart_by_position(self) -> None:
        sink = ReplySink()
        sink.owe_ack("x", awaited=False)
        waited = sink.owe_ack("x", awaited=True)

        sink.deliver(AckMessage(scene_id="x", ts=1.0))
        assert not sink.answered(waited)

        sink.deliver(AckMessage(scene_id="x", ts=2.0))
        assert sink.await_reply(waited, 0.0) == AckMessage(scene_id="x", ts=2.0)

    def test_an_ack_naming_another_scene_than_the_oldest_owed_is_refused(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a", awaited=True)

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
            sink.owe_ack(f"s{i}", awaited=False)
            sink.deliver(AckMessage(scene_id=f"s{i}"))

        assert sink.owed_acks == 0

    def test_a_scene_given_up_on_still_owes_its_ack_until_it_arrives(self) -> None:
        sink = ReplySink()
        owed = sink.owe_ack("a", awaited=True)

        sink.abandon(owed)
        assert sink.owed_acks == 1
        sink.deliver(AckMessage(scene_id="a"))

        assert not sink.answered(owed)
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
        timer = threading.Timer(0.05, sink.discard)
        timer.start()

        with pytest.raises(ConnectionClosedError, match="closed while a reply"):
            sink.await_reply(ping, 5.0)
        timer.join()

    def test_a_discarded_sink_takes_no_new_request(self) -> None:
        sink = ReplySink()
        sink.discard()

        with pytest.raises(ConnectionClosedError):
            sink.expect_query()
        with pytest.raises(ConnectionClosedError):
            sink.owe_ack("a", awaited=True)

    def test_discarding_drops_what_was_owed(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a", awaited=False)

        sink.discard()

        assert sink.owed_acks == 0


class TestARetiredDialNeverDelivers:
    def test_a_reply_delivered_after_the_discard_answers_nobody_and_raises_nothing(
        self,
    ) -> None:
        sink = ReplySink()
        ping = sink.expect_pong(1.0)
        sink.discard()

        sink.deliver(PongMessage(ts=1.0))
        sink.deliver(AckMessage(scene_id="stray"))  # not even a skew: it is retired
        sink.deliver(QueryResponse(method="m"))

        assert not sink.answered(ping)

    def test_a_reply_that_arrived_before_the_discard_is_still_taken(self) -> None:
        sink = ReplySink()
        ping = sink.expect_pong(1.0)
        sink.deliver(PongMessage(ts=1.0))

        sink.discard()

        assert sink.await_reply(ping, 0.0) == PongMessage(ts=1.0)


class TestTheClosedFlagIsOneHoldWithTheDiscard:
    """A delivery sees the closed flag in the same lock hold it puts in.

    The discard writes the flag under the sink's lock, and ``deliver`` reads it
    under that lock in the same hold as the put: a delivery that is waiting on the
    lock when the dial is retired sees the retirement and puts nothing.
    """

    def test_a_delivery_queued_behind_the_discard_sees_it(self) -> None:
        sink = ReplySink()
        outcome: list[BaseException | None] = []

        def deliver() -> None:
            try:
                sink.deliver(AckMessage(scene_id="stray"))  # owed nothing
            except ReplyOutOfOrderError as exc:
                outcome.append(exc)
            else:
                outcome.append(None)

        with sink._cond:  # the retirement holds the sink's lock
            thread = threading.Thread(target=deliver)
            thread.start()
            thread.join(timeout=0.1)
            assert thread.is_alive(), "the delivery did not wait for the lock"
            sink.discard()  # reentrant: the same hold writes the flag
        thread.join(timeout=3.0)

        assert outcome == [None], "the delivery read the flag before the hold"

    def test_a_stray_ack_before_the_discard_is_out_of_order(self) -> None:
        sink = ReplySink()

        with pytest.raises(ReplyOutOfOrderError):
            sink.deliver(AckMessage(scene_id="stray"))
