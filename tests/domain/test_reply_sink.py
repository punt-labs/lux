"""ReplySink -- a reply goes to the request it answers, or is dropped on arrival."""

from __future__ import annotations

import threading

import pytest

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.reply_sink import Pending, ReplyOutOfOrderError, ReplySink
from punt_lux.protocol import AckMessage, Message, PongMessage, QueryResponse


def _reply(pending: Pending) -> Message | None:
    """What the sink has handed ``pending`` so far (read fresh, never narrowed)."""
    return pending.reply


class TestAcks:
    def test_an_ack_goes_to_the_oldest_scene_owed(self) -> None:
        sink = ReplySink()
        first = sink.owe_ack("a", awaited=True)
        second = sink.owe_ack("b", awaited=True)

        sink.deliver(AckMessage(scene_id="a"))
        sink.deliver(AckMessage(scene_id="b"))

        assert (first.reply, second.reply) == (
            AckMessage(scene_id="a"),
            AckMessage(scene_id="b"),
        )

    def test_the_ack_of_a_scene_nobody_waits_for_is_popped_and_dropped(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a", awaited=False)
        waited = sink.owe_ack("b", awaited=True)

        sink.deliver(AckMessage(scene_id="a"))
        assert _reply(waited) is None
        sink.deliver(AckMessage(scene_id="b"))

        assert waited.reply == AckMessage(scene_id="b")
        assert sink.owed_acks == 0

    def test_a_scene_id_that_repeats_is_told_apart_by_position(self) -> None:
        sink = ReplySink()
        sink.owe_ack("x", awaited=False)
        waited = sink.owe_ack("x", awaited=True)

        sink.deliver(AckMessage(scene_id="x", ts=1.0))
        assert _reply(waited) is None

        sink.deliver(AckMessage(scene_id="x", ts=2.0))
        assert waited.reply == AckMessage(scene_id="x", ts=2.0)

    def test_an_ack_naming_another_scene_than_the_oldest_owed_is_refused(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a", awaited=True)

        with pytest.raises(ReplyOutOfOrderError, match="'b' arrived where 'a'"):
            sink.deliver(AckMessage(scene_id="b"))

    def test_an_ack_when_none_is_owed_is_dropped(self) -> None:
        sink = ReplySink()

        sink.deliver(AckMessage(scene_id="stray"))

        assert sink.owed_acks == 0

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

        assert owed.reply is None
        assert sink.owed_acks == 0


class TestPongs:
    def test_a_pong_answers_the_ping_whose_ts_it_echoes(self) -> None:
        sink = ReplySink()
        ping = sink.expect_pong(5.0)

        sink.deliver(PongMessage(ts=5.0))

        assert ping.reply == PongMessage(ts=5.0)

    def test_a_pong_for_another_ts_is_dropped(self) -> None:
        sink = ReplySink()
        ping = sink.expect_pong(5.0)

        sink.deliver(PongMessage(ts=4.0))

        assert ping.reply is None

    def test_a_repeated_pong_is_dropped(self) -> None:
        sink = ReplySink()
        sink.deliver(PongMessage(ts=1.0))
        ping = sink.expect_pong(1.0)
        sink.deliver(PongMessage(ts=1.0))
        sink.deliver(PongMessage(ts=1.0))

        assert ping.reply == PongMessage(ts=1.0)

    def test_a_pong_after_the_ping_was_abandoned_is_dropped(self) -> None:
        sink = ReplySink()
        ping = sink.expect_pong(1.0)
        sink.abandon(ping)

        sink.deliver(PongMessage(ts=1.0))

        assert ping.reply is None


class TestQueries:
    def test_a_response_answers_the_query_in_flight(self) -> None:
        sink = ReplySink()
        query = sink.expect_query()

        sink.deliver(QueryResponse(method="m"))

        assert query.reply == QueryResponse(method="m")

    def test_a_response_with_no_query_in_flight_is_dropped(self) -> None:
        sink = ReplySink()
        sink.deliver(QueryResponse(method="m"))
        query = sink.expect_query()

        assert sink.await_reply(query, 0.01) is None

    def test_a_second_response_is_dropped(self) -> None:
        sink = ReplySink()
        query = sink.expect_query()
        sink.deliver(QueryResponse(method="m", result={"n": 1}))
        sink.deliver(QueryResponse(method="m", result={"n": 2}))

        assert query.reply == QueryResponse(method="m", result={"n": 1})


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
