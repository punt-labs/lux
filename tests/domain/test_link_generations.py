"""The Hub's link against a scripted display: one reply for one request, per dial.

Each test drives a :class:`DisplayLink` over socket pairs and answers as a display
would, in the orders and failures that separate a reply from its request. A dial
makes a generation; nothing a generation received reaches a request made on
another, and an ack is matched to its scene by position.
"""

from __future__ import annotations

import contextlib
import queue
import threading
import time
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.clients import ClientRegistry
from punt_lux.domain.hub.connection_closed import (
    ConnectionClosedError,
    HubRetiredError,
)
from punt_lux.domain.hub.display_busy import DisplayBusyError
from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.display_listener import DisplayListener
from punt_lux.domain.hub.display_replies import DisplayReplies
from punt_lux.domain.hub.reply_sink import ReplySink
from punt_lux.domain.hub.request_exchange import RequestExchange
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import SceneId
from punt_lux.protocol import (
    AckMessage,
    HubManifestMessage,
    ObserverMessage,
    PingMessage,
    PongMessage,
    QueryRequest,
    QueryResponse,
    RemoteEventHandlerInvocation,
    SceneMessage,
    TextElement,
    encode_frame,
)
from tests.domain.display_double import Call, Display, until
from tests.link_access import generation_of, writer_of

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.protocol import Message


@pytest.fixture
def display() -> Iterator[Display]:
    d = Display()
    yield d
    d.close()


def _scene(scene_id: str) -> SceneMessage:
    return ScenePresentation(frame_id=scene_id).message(scene_id, [])


def _linked(
    display: Display, *, listening: bool = True, recv_timeout: float = 3.0
) -> DisplayLink:
    link = DisplayLink(display, recv_timeout=recv_timeout)
    link.connect()
    if listening:
        link.connect(listen=True)
    return link


class TestAcksAreMatchedByPosition:
    def test_acks_settle_the_ledger_in_write_order(self, display: Display) -> None:
        link = _linked(display)
        generation = generation_of(link)
        writer_of(link).send_scene(_scene("a"))
        writer_of(link).send_scene(_scene("b"))
        assert generation.owed_acks == 2

        display.peer.send(AckMessage(scene_id="a"))
        assert until(lambda: generation.owed_acks == 1)
        display.peer.send(AckMessage(scene_id="b"))

        assert until(lambda: generation.owed_acks == 0)
        assert link.is_connected
        link.close()

    def test_two_scenes_of_one_id_are_told_apart_by_count_not_by_id(
        self, display: Display
    ) -> None:
        link = _linked(display)
        generation = generation_of(link)
        writer_of(link).send_scene(_scene("x"))
        writer_of(link).send_scene(_scene("x"))

        display.peer.send(AckMessage(scene_id="x"))
        assert until(lambda: generation.owed_acks == 1)
        display.peer.send(AckMessage(scene_id="x", ts=2.0))

        assert until(lambda: generation.owed_acks == 0)
        link.close()

    def test_an_ack_that_names_another_scene_than_the_oldest_owed_ends_the_dial(
        self, display: Display
    ) -> None:
        link = _linked(display)
        writer_of(link).send_scene(_scene("a"))
        writer_of(link).send_scene(_scene("b"))
        display.peer.read(2)

        display.peer.send(AckMessage(scene_id="b"))

        assert until(lambda: not link.is_connected)

    def test_an_ack_nobody_is_owed_ends_the_dial(self, display: Display) -> None:
        # The ledger is entered under the socket lock before the reader can see
        # the matching bytes, so an ack with none owed means the streams disagree.
        link = _linked(display)

        display.peer.send(AckMessage(scene_id="unsolicited"))

        assert until(lambda: not link.is_connected)

    def test_without_a_listener_an_inline_read_settles_the_ledger_too(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        generation = generation_of(link)
        writer_of(link).send_scene(_scene("replicated"))
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (_scene_msg, ping) = display.peer.read(2)
        assert isinstance(ping, PingMessage)

        display.peer.send(AckMessage(scene_id="replicated"), PongMessage(ts=ping.ts))

        assert pinging.wait()
        assert generation.owed_acks == 0
        link.close()


class TestPongsAreMatchedByTheirTimestamp:
    def test_a_late_pong_does_not_answer_the_next_ping(self, display: Display) -> None:
        link = _linked(display)
        assert link.desk.asks().ping(timeout=0.2) is None
        (first,) = display.peer.read(1)
        assert isinstance(first, PingMessage)
        assert link.is_connected, "a ping that times out keeps its dial"

        second = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)
        display.peer.send(PongMessage(ts=first.ts), PongMessage(ts=sent.ts))

        assert second.wait()
        assert second.result == PongMessage(ts=sent.ts)
        link.close()

    def test_two_pings_within_one_clock_tick_carry_increasing_timestamps(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(time, "time", lambda: 1000.0)
        link = _linked(display)

        assert link.desk.asks().ping(timeout=0.05) is None
        assert link.desk.asks().ping(timeout=0.05) is None

        first, second = display.peer.read(2)
        assert isinstance(first, PingMessage)
        assert isinstance(second, PingMessage)
        assert first.ts is not None
        assert second.ts is not None
        assert second.ts > first.ts
        link.close()

    def test_a_query_response_with_no_query_in_flight_ends_the_dial(
        self, display: Display
    ) -> None:
        link = _linked(display)

        display.peer.send(QueryResponse(method="m"))

        assert until(lambda: not link.is_connected)

    def test_a_pong_with_no_ping_in_flight_is_dropped(self, display: Display) -> None:
        link = _linked(display)
        display.peer.send(PongMessage(ts=1.0))
        call = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        display.peer.send(PongMessage(ts=sent.ts))

        assert call.wait()
        assert call.result == PongMessage(ts=sent.ts)
        link.close()


class TestAQueryThatTimesOutRetiresItsDial:
    def test_the_connection_is_closed_and_a_late_response_answers_nothing(
        self, display: Display
    ) -> None:
        link = _linked(display)

        assert link.desk.asks().query("m", timeout=0.2) is None
        assert not link.is_connected
        (request,) = display.peers[0].read(1)
        assert isinstance(request, QueryRequest)
        with contextlib.suppress(OSError):  # the Hub hung up: a late reply has no road
            display.peers[0].send(QueryResponse(method="m", result={"late": True}))

        link.connect()
        link.connect(listen=True)
        again = Call(lambda: link.desk.asks().query("m", timeout=3.0))
        display.peers[1].read(1)
        display.peers[1].send(QueryResponse(method="m", result={"own": True}))

        assert again.wait()
        assert again.result == QueryResponse(method="m", result={"own": True})
        link.close()

    def test_a_ping_that_times_out_does_not_retire_its_dial(
        self, display: Display
    ) -> None:
        link = _linked(display)

        assert link.desk.asks().ping(timeout=0.1) is None

        assert link.is_connected
        link.close()


class TestRequestLocks:
    def test_a_budget_spent_waiting_for_the_lock_sends_nothing_and_retires_nothing(
        self, display: Display
    ) -> None:
        link = _linked(display)
        first = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        with pytest.raises(DisplayBusyError):
            link.desk.asks().ping(timeout=0.1)

        assert link.is_connected
        assert display.peer.read(1, timeout=0.2) == [], "the second ping wrote nothing"
        display.peer.send(PongMessage(ts=sent.ts))
        assert first.wait()
        assert first.result == PongMessage(ts=sent.ts)
        link.close()

    def test_a_liveness_ping_is_not_held_behind_a_slow_query(
        self, display: Display
    ) -> None:
        link = _linked(display)
        slow = Call(lambda: link.desk.asks().query("slow", timeout=3.0))
        (request,) = display.peer.read(1)
        assert isinstance(request, QueryRequest)

        probe = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)
        display.peer.send(PongMessage(ts=sent.ts))

        assert probe.wait(1.0)
        assert probe.result == PongMessage(ts=sent.ts)
        display.peer.send(QueryResponse(method="slow"))
        assert slow.wait()
        link.close()


class TestARedialBetweenSendAndWait:
    def test_the_waiter_fails_and_never_consumes_the_new_dial_s_reply(
        self, display: Display
    ) -> None:
        link = _linked(display)
        call = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        link.close()
        link.connect()
        link.connect(listen=True)
        display.peers[1].send(PongMessage(ts=sent.ts))

        assert call.wait()
        assert isinstance(call.error, ConnectionClosedError)
        link.close()

    def test_without_a_listener_the_wait_fails_instead_of_reading_the_new_socket(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        call = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        link.close()
        link.connect()
        display.peers[1].send(PongMessage(ts=sent.ts))

        assert call.wait()
        assert isinstance(call.error, ConnectionClosedError)
        link.close()


class TestAWriteThatRaises:
    def test_it_retires_its_dial_and_the_next_scene_is_owed_on_the_new_one(
        self, display: Display
    ) -> None:
        link = _linked(display)
        display.sockets[0].fail_next_send = True

        with pytest.raises(OSError, match="fell over"):
            writer_of(link).send_scene(_scene("lost"))
        assert not link.is_connected

        link.connect()
        link.connect(listen=True)
        writer_of(link).send_scene(_scene("next"))
        display.peers[1].read(1)
        generation = generation_of(link)
        assert generation.owed_acks == 1  # the lost scene is owed nothing, this is
        display.peers[1].send(AckMessage(scene_id="next"))

        assert until(lambda: generation.owed_acks == 0)
        link.close()


class TestAnInterruptedWriteRetiresItsDial:
    @pytest.mark.parametrize("failure", [ValueError("boom"), KeyboardInterrupt()])
    def test_whatever_interrupts_a_write_leaves_the_stream_unaligned(
        self,
        display: Display,
        monkeypatch: pytest.MonkeyPatch,
        failure: BaseException,
    ) -> None:
        # Bytes may already be on the wire, so the frame stream cannot be trusted.
        link = _linked(display)

        def interrupted(_data: bytes) -> None:
            raise failure

        monkeypatch.setattr(display.sockets[0], "sendall", interrupted)

        with pytest.raises(type(failure)):
            writer_of(link).send_scene(_scene("x"))

        assert not link.is_connected

    def test_a_refusal_before_any_byte_is_written_retires_nothing(
        self, display: Display
    ) -> None:
        link = _linked(display)
        dial = generation_of(link)
        dial.send_ping(1.0)  # a ping is in flight on the dial

        with pytest.raises(RuntimeError, match="already in flight"):
            dial.send_ping(2.0)

        assert link.is_connected
        assert display.peer.read(2, timeout=0.2)[1:] == [], "the second ping wrote"


class TestAStoppedListenerEndsItsDial:
    def test_stopping_the_listener_closes_the_connection(
        self, display: Display
    ) -> None:
        link = _linked(display)

        link.close()

        assert not link.is_connected

    def test_a_reply_waiting_when_the_listener_stops_fails_at_once(
        self, display: Display
    ) -> None:
        link = _linked(display)
        call = Call(lambda: link.desk.asks().ping(timeout=3.0))
        display.peer.read(1)

        link.close()

        assert call.wait(1.0)
        assert isinstance(call.error, ConnectionClosedError)


class TestOneSocketOneCallerAtATime:
    def test_a_read_and_a_write_of_two_request_kinds_never_overlap_on_the_socket(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        waiting = Call(lambda: link.desk.asks().query("slow", timeout=3.0))
        (request,) = display.peer.read(1)
        assert isinstance(request, QueryRequest)

        probes = [Call(lambda: link.desk.asks().ping(timeout=0.3)) for _ in range(3)]
        for probe in probes:
            probe.wait()
        display.peer.send(QueryResponse(method="slow"))

        assert waiting.wait()
        assert display.sockets[0].overlaps == 0
        link.close()


class TestEventsAfterTheListenerEndedTheConnection:
    def test_queued_events_are_delivered_then_the_wait_times_out_naming_the_exit(
        self, display: Display
    ) -> None:
        link = _linked(display)
        display.peer.send(ObserverMessage(topic="t", payload={"n": 1}))
        display.peer.close()
        assert until(lambda: not link.is_connected)

        event = link.events.poll_event(1.0)
        with pytest.raises(TimeoutError, match="listener thread has exited"):
            link.events.poll_event(0.05)

        assert event.topic == "t"

    def test_it_is_the_same_whichever_thread_wins_the_race(
        self, display: Display
    ) -> None:
        link = _linked(display)
        display.peer.close()

        with pytest.raises(TimeoutError, match="has exited"):
            link.events.poll_event(0.2)


class TestBusyIsNotDead:
    def test_a_lock_wait_expiry_on_ping_says_busy_not_no_pong(
        self, display: Display
    ) -> None:
        link = _linked(display)
        first = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        with pytest.raises(DisplayBusyError):
            link.desk.asks().ping(timeout=0.05)

        display.peer.send(PongMessage(ts=sent.ts))
        assert first.wait()
        link.close()

    def test_a_probe_that_finds_a_ping_in_flight_does_not_report_a_dead_display(
        self, display: Display
    ) -> None:
        link = _linked(display)
        first = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        assert link.desk.asks().probe_alive(0.05) is True

        assert display.peer.read(1, timeout=0.1) == []
        display.peer.send(PongMessage(ts=sent.ts))
        assert first.wait()
        link.close()

    def test_a_confirmation_that_only_finds_a_ping_in_flight_kills_nothing(
        self, display: Display
    ) -> None:
        # The isolation loop must learn that the display survived the scene it just
        # sent. A ping already in flight proves nothing about that scene, and says
        # nothing against the display: the confirmation waits it out, asks again, and
        # a dial that stays busy is not a death.
        link = _linked(display)
        first = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        assert link.desk.asks().confirm_alive(0.05) is True

        assert display.peer.read(1, timeout=0.1) == [], "a busy dial wrote nothing"
        display.peer.send(PongMessage(ts=sent.ts))
        assert first.wait()
        link.close()

    def test_a_confirmation_that_waited_out_a_ping_gets_the_displays_own_pong(
        self, display: Display
    ) -> None:
        link = _linked(display)
        first = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)
        confirming = Call(lambda: link.desk.asks().confirm_alive(1.0))
        time.sleep(0.1)  # the confirmation is queued behind the first ping

        display.peer.send(PongMessage(ts=sent.ts))
        (own,) = display.peer.read(1)
        assert isinstance(own, PingMessage), "the confirmation asked again"
        display.peer.send(PongMessage(ts=own.ts))

        assert first.wait()
        assert confirming.wait()
        assert confirming.result is True
        link.close()

    def test_a_confirmation_is_the_displays_own_pong(self, display: Display) -> None:
        link = _linked(display)
        confirming = Call(lambda: link.desk.asks().confirm_alive(3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        display.peer.send(PongMessage(ts=sent.ts))

        assert confirming.wait()
        assert confirming.result is True
        link.close()

    def test_a_confirmation_the_display_never_answers_is_false(
        self, display: Display
    ) -> None:
        link = _linked(display)

        assert link.desk.asks().confirm_alive(0.05) is False
        link.close()

    def test_a_query_that_lost_its_lock_wait_says_busy_and_keeps_its_dial(
        self, display: Display
    ) -> None:
        link = _linked(display)
        slow = Call(lambda: link.desk.asks().query("slow", timeout=3.0))
        display.peer.read(1)

        with pytest.raises(DisplayBusyError):
            link.desk.asks().query("other", timeout=0.05)

        assert link.is_connected
        assert display.peer.read(1, timeout=0.2) == [], "the second query wrote nothing"
        link.close()
        assert slow.wait()


class TestTheLockWaitAndTheReplyWaitAreSeparateBudgets:
    def test_a_query_that_won_the_lock_late_still_gets_its_whole_reply_wait(
        self, display: Display
    ) -> None:
        link = _linked(display)
        first = Call(lambda: link.desk.asks().query("first", timeout=3.0))
        display.peer.read(1)
        second = Call(lambda: link.desk.asks().query("second", timeout=0.6))
        time.sleep(0.4)  # the second has waited most of its budget for the lock

        display.peer.send(QueryResponse(method="first"))
        assert first.wait()
        (request,) = display.peer.read(1)
        assert isinstance(request, QueryRequest)
        time.sleep(0.4)  # slower than the budget the lock wait left over
        display.peer.send(QueryResponse(method="second", result={"late": True}))

        assert second.wait()
        assert second.result == QueryResponse(method="second", result={"late": True})
        assert link.is_connected, "a live display answered; nothing may retire its dial"
        link.close()


class TestARetiredDialNeverDelivers:
    def test_the_rest_of_a_chunk_is_not_routed_once_its_dial_is_retired(
        self, display: Display
    ) -> None:
        link = _linked(display)
        link.events.set_fallback_handler(lambda _event: link._connection.close())
        click = RemoteEventHandlerInvocation(element_id="b", action="click")

        display.peer.send(click, ObserverMessage(topic="after", payload={}))

        assert until(lambda: not link.is_connected)
        with pytest.raises(TimeoutError):
            link.events.poll_event(0.3)  # the retired dial's events never arrive

    def test_the_rest_of_a_chunk_read_inline_is_not_routed_once_its_dial_is_retired(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = _linked(display, listening=False)
        real_route = DisplayListener.route

        def retiring_route(
            listener: DisplayListener,
            generation: DialGeneration,
            msg: Message,
            *,
            inline: bool,
        ) -> None:
            real_route(listener, generation, msg, inline=inline)
            if isinstance(msg, ObserverMessage) and msg.topic == "first":
                link._connection.close()  # retired mid-chunk

        monkeypatch.setattr(DisplayListener, "route", retiring_route)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        display.peer.send(
            ObserverMessage(topic="first", payload={}),
            ObserverMessage(topic="after", payload={}),
            PongMessage(ts=sent.ts),
        )

        assert pinging.wait()
        assert isinstance(pinging.error, ConnectionClosedError)
        topics: list[str] = []
        with contextlib.suppress(queue.Empty):
            while True:
                topics.append(link._listener._inbound.next_event(0.1).topic)
        assert topics == ["first"], "the retired dial's later message was routed"


class TestOneReaderPerDial:
    def test_a_listener_started_during_an_inline_wait_waits_for_it(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        starting = Call(lambda: link.connect(listen=True))
        assert not starting.wait(0.3), (
            "the inline read holds the dial's one reader slot"
        )
        display.peer.send(PongMessage(ts=sent.ts))

        assert pinging.wait()
        assert starting.wait()
        assert generation_of(link).has_reader
        assert display.sockets[0].reader_overlaps == 0
        link.close()

    def test_two_request_kinds_waiting_inline_share_one_reader_and_both_are_answered(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        querying = Call(lambda: link.desk.asks().query("m", timeout=3.0))
        display.peer.read(1)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        display.peer.send(
            PongMessage(ts=sent.ts), QueryResponse(method="m", result={"n": 1})
        )

        assert pinging.wait()
        assert querying.wait()
        assert pinging.result == PongMessage(ts=sent.ts)
        assert querying.result == QueryResponse(method="m", result={"n": 1})
        assert display.sockets[0].reader_overlaps == 0
        link.close()


class TestAnInlineReadRoutesWhatTheListenerWould:
    def test_a_click_read_while_waiting_inline_reaches_the_handler(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        seen: list[RemoteEventHandlerInvocation] = []
        link.events.set_fallback_handler(seen.append)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        click = RemoteEventHandlerInvocation(element_id="b", action="click")
        display.peer.send(click, PongMessage(ts=sent.ts))

        assert pinging.wait()
        assert seen == [click]
        link.close()

    def test_a_business_event_read_inline_is_queued_for_poll_event(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        display.peer.send(
            ObserverMessage(topic="t", payload={"n": 1}), PongMessage(ts=sent.ts)
        )

        assert pinging.wait()
        link.connect(listen=True)
        assert link.events.poll_event(1.0).topic == "t"
        link.close()


class TestInlineReadingKeepsTheSocketLockShort:
    def test_a_ping_is_written_promptly_while_a_query_waits_inline_and_replies_stream(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        querying = Call(lambda: link.desk.asks().query("slow", timeout=5.0))
        display.peer.read(1)
        streaming = threading.Event()

        def stream() -> None:
            while not streaming.is_set():
                with contextlib.suppress(OSError):
                    display.peer.send(PongMessage(ts=0.5))  # matches nothing: dropped
                time.sleep(0.01)

        streamer = threading.Thread(target=stream, daemon=True)
        streamer.start()
        try:
            probe = Call(lambda: link.desk.asks().ping(timeout=3.0))
            (sent,) = display.peer.read(1, timeout=0.5)

            assert isinstance(sent, PingMessage), "the ping was not written in 0.5 s"
            display.peer.send(PongMessage(ts=sent.ts))
            assert probe.wait()
            assert display.sockets[0].overlaps == 0
        finally:
            streaming.set()
            streamer.join(1.0)
            display.peer.send(QueryResponse(method="slow"))
            assert querying.wait()
            link.close()

    def test_a_ping_is_written_promptly_while_a_query_waits_inline_on_a_silent_peer(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        querying = Call(lambda: link.desk.asks().query("slow", timeout=5.0))
        display.peer.read(1)

        probe = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1, timeout=0.5)

        assert isinstance(sent, PingMessage), "the wait held the socket lock in select"
        display.peer.send(PongMessage(ts=sent.ts), QueryResponse(method="slow"))
        assert probe.wait()
        assert querying.wait()
        link.close()


class TestRacingWritersAreReleasedByRetirement:
    def test_two_writers_against_a_wedged_peer_are_both_released_by_close(
        self, display: Display
    ) -> None:
        link = _linked(display)
        big = ScenePresentation(frame_id="big").message(
            "big", [TextElement(id="t", content="x" * (8 * 1024 * 1024))]
        )
        replicating = Call(lambda: writer_of(link).send_scene(big))
        assert not replicating.wait(0.3), "the peer reads nothing: the write wedges"
        showing = Call(lambda: writer_of(link).send_scene(_scene("next")))
        assert not showing.wait(0.2), "the second writer waits behind the wedged one"

        link.close()  # retire: shutdown wakes the sender and frees the socket lock

        assert replicating.wait(3.0)
        assert showing.wait(3.0)
        assert isinstance(replicating.error, OSError)


class TestEveryRetirementReachesTheRegistry:
    """Rule 9: whatever retires a dial, the registry redials and reconciles."""

    @staticmethod
    def _registry(display: Display) -> tuple[ClientRegistry, DisplayLink]:
        registry = ClientRegistry()
        link = DisplayLink(display, recv_timeout=3.0)
        registry._client = link
        registry.asks()
        return registry, link

    @staticmethod
    def _redialed(display: Display, registry: ClientRegistry) -> None:
        registry.asks()
        assert display.dials == 2
        (first,) = display.peers[1].read(1)
        assert isinstance(first, HubManifestMessage)

    def test_a_reader_that_ends(self, display: Display) -> None:
        registry, link = self._registry(display)
        display.peers[0].close()
        assert until(lambda: not link.is_connected)

        self._redialed(display, registry)

        assert generation_of(link).has_reader
        link.close()

    def test_a_query_that_times_out(self, display: Display) -> None:
        registry, link = self._registry(display)
        assert link.desk.asks().query("m", timeout=0.1) is None

        self._redialed(display, registry)

        assert generation_of(link).has_reader
        link.close()

    def test_a_torn_write(self, display: Display) -> None:
        registry, link = self._registry(display)
        display.sockets[0].fail_next_send = True
        with pytest.raises(OSError, match="fell over"):
            writer_of(link).send_scene(_scene("s"))

        self._redialed(display, registry)

        assert generation_of(link).has_reader
        link.close()


class TestDropNamesTheDialThatFailed:
    """R1: a caller that saw its own dial fail never closes a newer one."""

    @staticmethod
    def _registry(display: Display) -> tuple[ClientRegistry, DisplayLink]:
        registry = ClientRegistry()
        link = DisplayLink(display, recv_timeout=3.0)
        registry._client = link
        registry.asks()
        return registry, link

    def test_a_drop_for_a_replaced_dial_leaves_the_new_dial_open(
        self, display: Display
    ) -> None:
        registry, link = self._registry(display)
        failed = link.desk.asks().dial
        link._connection.close()  # another thread retired it and redialed
        registry.asks()

        registry.drop(failed)

        assert link.is_connected
        assert display.dials == 2
        link.close()

    def test_a_drop_for_the_current_dial_closes_it(self, display: Display) -> None:
        registry, link = self._registry(display)

        registry.drop(link.desk.asks().dial)

        assert not link.is_connected
        link.close()

    def test_a_drop_in_a_registry_with_no_link_touches_no_other_link(self) -> None:
        registry = ClientRegistry()
        display = Display()
        link = DisplayLink(display)
        link.connect()
        generation = link.desk.asks().dial

        registry.drop(generation)  # no client in this registry: nothing to retire

        assert link.is_connected
        link.close()
        display.close()


class TestWhoEndedADialIsWhatARetiredSenderLearns:
    def test_a_dial_the_display_closed_reports_a_plain_closed_connection(
        self, display: Display
    ) -> None:
        link = _linked(display)
        dial = generation_of(link)

        display.peer.close()
        assert until(lambda: not link.is_connected)

        with pytest.raises(ConnectionClosedError) as caught:
            dial.send(PingMessage(ts=1.0))
        assert not isinstance(caught.value, HubRetiredError)

    def test_a_dial_a_query_timeout_retired_reports_the_hub_retired_it(
        self, display: Display
    ) -> None:
        link = _linked(display)
        dial = generation_of(link)

        assert link.desk.asks().query("m", timeout=0.1) is None

        with pytest.raises(HubRetiredError):
            dial.send(PingMessage(ts=1.0))

    def test_a_dial_a_skewed_reply_retired_reports_the_hub_retired_it(
        self, display: Display
    ) -> None:
        link = _linked(display)
        dial = generation_of(link)

        display.peer.send(AckMessage(scene_id="unsolicited"))
        assert until(lambda: not link.is_connected)

        with pytest.raises(HubRetiredError):
            dial.send(PingMessage(ts=1.0))

    def test_a_dial_the_hub_closed_deliberately_reports_the_hub_retired_it(
        self, display: Display
    ) -> None:
        link = _linked(display)
        dial = generation_of(link)

        link.close()

        with pytest.raises(HubRetiredError):
            dial.send(PingMessage(ts=1.0))


class TestAPeerThatStopsReading:
    def test_the_wedged_writer_ends_within_the_send_bound_and_releases_the_queue(
        self, display: Display
    ) -> None:
        link = _linked(display)
        big = ScenePresentation(frame_id="big").message(
            "big", [TextElement(id="t", content="x" * (8 * 1024 * 1024))]
        )
        began = time.monotonic()
        replicating = Call(lambda: writer_of(link).send_scene(big))
        assert not replicating.wait(0.3), "the peer reads nothing: the write wedges"
        showing = Call(lambda: writer_of(link).send_scene(_scene("next")))
        pinging = Call(lambda: link.desk.asks().ping(timeout=5.0))

        assert replicating.wait(5.0), "the send timeout did not end the wedged write"
        assert isinstance(replicating.error, OSError)
        assert until(lambda: not link.is_connected)
        assert showing.wait(5.0)
        assert pinging.wait(5.0)
        assert time.monotonic() - began < 5.0
        assert isinstance(showing.error, OSError)
        assert isinstance(pinging.error, OSError)

    def test_every_dial_s_socket_carries_the_send_timeout(
        self, display: Display
    ) -> None:
        link = _linked(display)
        assert display.sockets[0].has_send_timeout()

        link.close()
        link.connect()  # a redial gets it too

        assert display.sockets[1].has_send_timeout()
        link.close()


class TestRegistryLocksAreNotHeldUnderTheModelsLocks:
    def test_a_query_timeout_retires_without_calling_the_registry(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry = ClientRegistry()
        link = DisplayLink(display, recv_timeout=3.0)
        registry._client = link
        registry.asks()

        def forbidden() -> None:
            pytest.fail("the retire went through ClientRegistry.drop() under a lock")

        monkeypatch.setattr(registry, "drop", forbidden)

        assert link.desk.asks().query("m", timeout=0.1) is None
        assert not link.is_connected
        link.close()


class TestConnectCoordinatesTheDialAndItsListener:
    def test_connect_with_listen_starts_the_reader_on_the_new_dial(
        self, display: Display
    ) -> None:
        link = DisplayLink(display, recv_timeout=3.0)

        link.connect(listen=True)

        assert generation_of(link).has_reader
        link.close()

    def test_connect_alone_starts_no_reader(self, display: Display) -> None:
        link = DisplayLink(display, recv_timeout=3.0)

        link.connect()

        assert not generation_of(link).has_reader
        link.close()


class TestAnInlineReadThatFails:
    def test_a_frame_of_an_admitted_type_that_cannot_be_decoded_retires_the_dial(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        display.peer.read(1)

        display.peer.send_raw(encode_frame({"type": "ack"}))  # no scene_id: KeyError

        assert pinging.wait()
        assert pinging.error is not None
        assert not link.is_connected

    def test_a_reply_whose_delivery_raises_retires_the_dial(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(_sink: ReplySink, _msg: object) -> None:
            raise RuntimeError("the sink blew up")

        monkeypatch.setattr(ReplySink, "deliver", explode)
        link = _linked(display, listening=False)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        display.peer.send(PongMessage(ts=sent.ts))

        assert pinging.wait()
        assert isinstance(pinging.error, RuntimeError)
        assert not link.is_connected


class TestTheClosedMarkIsOneHoldWithTheSinkDiscard:
    """A dial reads as closed only in the hold that refuses its sink's deliveries."""

    def test_a_dial_does_not_read_as_closed_while_a_delivery_holds_the_sink(
        self, display: Display
    ) -> None:
        link = _linked(display)
        generation = generation_of(link)

        with generation._sink._cond:  # test seam: a reader mid-delivery holds it
            closing = Call(lambda: generation.mark_closed("display"))
            time.sleep(0.1)
            assert not generation.is_closed, "closed before the sink refused replies"

        assert closing.wait()
        assert generation.is_closed

    def test_a_reply_delivered_once_the_dial_reads_closed_is_parked_for_nobody(
        self, display: Display
    ) -> None:
        link = _linked(display)
        generation = generation_of(link)
        pending = generation.send_ping(1.0)
        generation.mark_closed("display")

        assert generation.is_closed
        generation.deliver(PongMessage(ts=1.0))

        assert not generation.answered(pending)


class TestTheRegistryNeverWaitsOnTheReaderSlot:
    def test_asks_on_a_connected_link_returns_while_an_inline_read_holds_the_slot(
        self, display: Display
    ) -> None:
        registry = ClientRegistry()
        link = DisplayLink(display, recv_timeout=3.0)
        registry._client = link
        link.connect()  # a dial with no reader, as a library caller leaves it
        generation = link._connection.require()
        holding = threading.Event()
        release = threading.Event()

        def hold_the_slot() -> None:
            with generation.inline_reading():
                holding.set()
                release.wait(5.0)

        holder = threading.Thread(target=hold_the_slot, daemon=True)
        holder.start()
        assert holding.wait(3.0)

        getting = Call(registry.asks)
        try:
            assert getting.wait(0.5), "asks() waited on the reader slot under its lock"
        finally:
            release.set()
            holder.join(3.0)
            link.close()

    def test_a_dial_the_registry_makes_already_has_its_reader(
        self, display: Display
    ) -> None:
        registry = ClientRegistry()
        link = DisplayLink(display, recv_timeout=3.0)
        registry._client = link

        registry.asks()

        assert generation_of(link).has_reader
        link.close()


def _ping_lock_is_held(link: DisplayLink) -> bool:
    """Whether a ping made now finds the ping lock taken (busy, nothing sent)."""
    try:
        link.desk.asks().ping(timeout=0.05)
    except DisplayBusyError:
        return True
    return False


class TestAnInteractionReadInlineRunsOutsideTheLocks:
    def test_the_handler_runs_after_the_exchange_with_no_request_lock_or_slot_held(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        seen: list[tuple[bool, bool]] = []

        def handler(_event: RemoteEventHandlerInvocation) -> None:
            with generation_of(link).inline_reading() as free:
                seen.append((_ping_lock_is_held(link), free))

        link.events.set_fallback_handler(handler)
        pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        click = RemoteEventHandlerInvocation(element_id="b", action="click")
        display.peer.send(click, PongMessage(ts=sent.ts))

        assert pinging.wait()
        assert seen == [(False, True)]
        link.close()


class TestAFailedListenerStartRetiresItsDial:
    def test_connect_with_listen_retires_the_dial_it_made_when_the_start_fails(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = DisplayLink(display, recv_timeout=3.0)

        def refuse(_thread: threading.Thread) -> None:
            raise RuntimeError("can't start new thread")

        monkeypatch.setattr(threading.Thread, "start", refuse)
        with pytest.raises(RuntimeError, match="can't start"):
            link.connect(listen=True)

        assert not link.is_connected, "a connected link with no reader repairs nothing"

    def test_the_registry_redials_with_a_reader_after_a_failed_start(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry = ClientRegistry()
        link = DisplayLink(display, recv_timeout=3.0)
        registry._client = link

        with monkeypatch.context() as patched:

            def refuse(_thread: threading.Thread) -> None:
                raise RuntimeError("can't start new thread")

            patched.setattr(threading.Thread, "start", refuse)
            with pytest.raises(RuntimeError, match="can't start"):
                registry.asks()
        assert not link.is_connected

        registry.asks()

        assert display.dials == 2
        assert generation_of(link).has_reader
        link.close()


class TestAnInteractionRunsBeforeItsExchangeReturns:
    def test_the_handler_has_run_by_the_time_the_ping_returns(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        returned = threading.Event()
        ran_before_return: list[bool] = []
        link.events.set_fallback_handler(
            lambda _event: ran_before_return.append(not returned.is_set())
        )

        def ping() -> object:
            try:
                return link.desk.asks().ping(timeout=3.0)
            finally:
                returned.set()

        pinging = Call(ping)
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)
        display.peer.send(
            RemoteEventHandlerInvocation(element_id="b", action="click"),
            PongMessage(ts=sent.ts),
        )

        assert pinging.wait()
        assert ran_before_return == [True], "the click waited past its own exchange"
        link.close()


class TestARequestIsPinnedToTheDialItWasMadeFor:
    """A redial between two requests fails the second; it never rides the new dial."""

    def test_a_ping_after_a_redial_fails_with_the_old_dials_error(
        self, display: Display
    ) -> None:
        link = _linked(display)
        port = link.desk.asks()
        link.close()
        link.connect(listen=True)  # a new dial the port was not made for

        with pytest.raises(HubRetiredError):
            port.ping(timeout=0.1)

        assert display.peer.read(1, timeout=0.2) == [], "the ping rode the new dial"
        link.close()

    def test_a_query_after_a_redial_fails_with_the_old_dials_error(
        self, display: Display
    ) -> None:
        link = _linked(display)
        port = link.desk.asks()
        link.close()
        link.connect(listen=True)

        with pytest.raises(HubRetiredError):
            port.query("m", timeout=0.1)

        assert display.peer.read(1, timeout=0.2) == []
        link.close()

    def test_a_write_after_a_redial_fails_with_the_old_dials_error(
        self, display: Display
    ) -> None:
        link = _linked(display)
        writer = writer_of(link)
        link.close()
        link.connect(listen=True)

        with pytest.raises(HubRetiredError):
            writer.send_scene(_scene("x"))

        assert display.peer.read(1, timeout=0.2) == []
        link.close()

    def test_the_dial_a_port_names_is_the_dial_it_was_made_for(
        self, display: Display
    ) -> None:
        registry = ClientRegistry()
        link = DisplayLink(display, recv_timeout=3.0)
        registry._client = link
        registry.asks()
        port = link.desk.asks()
        link._connection.close()  # another thread retired it and redialed
        registry.asks()

        registry.drop(port.dial)  # names the dial the port was made for

        assert link.is_connected, "the drop closed the successor"
        link.close()


class TestTheWriteSeatIsHandedOutOnce:
    def test_a_second_asker_is_refused(self, display: Display) -> None:
        link = DisplayLink(display, recv_timeout=3.0)
        link.desk.take_seat()

        with pytest.raises(ValueError, match="already handed"):
            link.desk.take_seat()

    def test_the_registry_hands_the_link_s_seat_out_once(
        self, display: Display
    ) -> None:
        registry = ClientRegistry()
        registry._client = DisplayLink(display, recv_timeout=3.0)
        registry.take_writer()

        with pytest.raises(ValueError, match="already handed"):
            registry.take_writer()


class TestDeclaringWhatTheHubHolds:
    def test_the_manifest_names_every_scene_the_hub_declares(
        self, display: Display
    ) -> None:
        link = DisplayLink(display, recv_timeout=3.0)

        declared = link.connect(
            listen=True, manifest=lambda: (SceneId("a"), SceneId("b"))
        )

        (sent,) = display.peer.read(1)
        assert sent == HubManifestMessage(scene_ids=("a", "b"))
        assert declared == ("a", "b")
        link.close()

    def test_the_manifest_is_read_after_the_dial_is_made(
        self, display: Display
    ) -> None:
        link = DisplayLink(display, recv_timeout=3.0)
        dials_when_read: list[int] = []

        def manifest() -> tuple[SceneId, ...]:
            dials_when_read.append(display.dials)
            return ()

        link.connect(listen=True, manifest=manifest)

        assert dials_when_read == [1]
        link.close()

    def test_a_manifest_that_cannot_be_sent_closes_the_link_and_raises(
        self, display: Display
    ) -> None:
        link = DisplayLink(display, recv_timeout=3.0)

        def failing_manifest() -> tuple[SceneId, ...]:
            display.sockets[-1].fail_next_send = True
            return (SceneId("a"),)

        with pytest.raises(OSError, match="fell over"):
            link.connect(listen=True, manifest=failing_manifest)

        assert not link.is_connected


class TestAPingIsStampedUnderItsLock:
    def test_the_stamp_is_made_only_inside_the_hold_and_the_hold_is_exclusive(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A clock that stands still: the stamps must rise on their own.
        monkeypatch.setattr(
            "punt_lux.domain.hub.request_exchange.time.time", lambda: 5.0
        )
        connection = DisplayConnection(display, 1.0)
        exchange = RequestExchange(
            connection,
            DisplayReplies(connection, DisplayListener(connection, 1.0)),
            1.0,
        )

        with exchange.exclusive("ping") as first:
            assert first > 0
            with pytest.raises(DisplayBusyError):  # a second ping cannot stamp
                second_ping = exchange.exclusive("ping", 0.01)
                with second_ping:
                    pass
        with exchange.exclusive("ping") as second:
            assert second > first

    def test_the_stamps_pings_carry_only_ever_rise(self, display: Display) -> None:
        link = _linked(display)
        stamps: list[float] = []
        for _ in range(3):
            pinging = Call(lambda: link.desk.asks().ping(timeout=3.0))
            (sent,) = display.peer.read(1)
            assert isinstance(sent, PingMessage)
            stamps.append(float(sent.ts or 0.0))
            display.peer.send(PongMessage(ts=sent.ts))
            assert pinging.wait()

        assert stamps == sorted(set(stamps))
        link.close()
