"""The Hub's link against a scripted display: one reply for one request, per dial.

Each test drives a :class:`DisplayLink` over socket pairs and answers as a display
would, in the orders and failures that separate a reply from its request. A dial
makes a generation; nothing a generation received reaches a request made on
another, and an ack is matched to its scene by position.
"""

from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.clients import ClientRegistry
from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.display_busy import DisplayBusyError
from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.scene_presentation import ScenePresentation
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
)
from tests.domain.display_double import Call, Display, until

if TYPE_CHECKING:
    from collections.abc import Iterator


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
    link = DisplayLink(dialer=display, auto_spawn=False, recv_timeout=recv_timeout)
    link.connect()
    if listening:
        link.start_listener()
    return link


class TestAcksAreMatchedByPosition:
    def test_a_show_after_a_scene_nobody_waits_for_gets_its_own_ack(
        self, display: Display
    ) -> None:
        link = _linked(display)
        link.requests.send_scene(_scene("replicated"))
        shown = Call(lambda: link.requests.show("shown", []))
        scenes = display.peer.read(2)
        assert [s.id for s in scenes if isinstance(s, SceneMessage)] == [
            "replicated",
            "shown",
        ]

        display.peer.send(AckMessage(scene_id="replicated"), AckMessage("shown"))

        assert shown.wait()
        assert shown.result == AckMessage(scene_id="shown")
        link.close()

    def test_two_scenes_of_one_id_are_told_apart_by_count_not_by_id(
        self, display: Display
    ) -> None:
        link = _linked(display)
        link.requests.send_scene(_scene("x"))
        shown = Call(lambda: link.requests.show("x", []))
        display.peer.read(2)

        display.peer.send(AckMessage(scene_id="x"))
        assert not shown.wait(0.3), "the first ack of x belongs to the replicated scene"
        display.peer.send(AckMessage(scene_id="x", ts=2.0))

        assert shown.wait()
        assert shown.result == AckMessage(scene_id="x", ts=2.0)
        link.close()

    def test_an_ack_that_names_another_scene_than_the_oldest_owed_ends_the_dial(
        self, display: Display
    ) -> None:
        link = _linked(display)
        link.requests.send_scene(_scene("a"))
        link.requests.send_scene(_scene("b"))
        display.peer.read(2)

        display.peer.send(AckMessage(scene_id="b"))

        assert until(lambda: not link.is_connected)

    def test_an_ack_nobody_is_owed_is_dropped_and_the_dial_survives(
        self, display: Display
    ) -> None:
        link = _linked(display)
        display.peer.send(AckMessage(scene_id="unsolicited"))
        time.sleep(0.3)  # the reader has taken it before any scene is owed
        shown = Call(lambda: link.requests.show("s", []))
        display.peer.read(1)
        display.peer.send(AckMessage(scene_id="s"))

        assert shown.wait()
        assert link.is_connected
        link.close()

    def test_without_a_listener_a_show_still_gets_its_own_ack(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        link.requests.send_scene(_scene("replicated"))
        shown = Call(lambda: link.requests.show("shown", []))
        display.peer.read(2)

        display.peer.send(AckMessage(scene_id="replicated"), AckMessage("shown"))

        assert shown.wait()
        assert shown.result == AckMessage(scene_id="shown")
        link.close()


class TestPongsAreMatchedByTheirTimestamp:
    def test_a_late_pong_does_not_answer_the_next_ping(self, display: Display) -> None:
        link = _linked(display)
        assert link.requests.ping(timeout=0.2) is None
        (first,) = display.peer.read(1)
        assert isinstance(first, PingMessage)
        assert link.is_connected, "a ping that times out keeps its dial"

        second = Call(lambda: link.requests.ping(timeout=3.0))
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

        assert link.requests.ping(timeout=0.05) is None
        assert link.requests.ping(timeout=0.05) is None

        first, second = display.peer.read(2)
        assert isinstance(first, PingMessage)
        assert isinstance(second, PingMessage)
        assert first.ts is not None
        assert second.ts is not None
        assert second.ts > first.ts
        link.close()

    def test_a_pong_with_no_ping_in_flight_is_dropped(self, display: Display) -> None:
        link = _linked(display)
        display.peer.send(PongMessage(ts=1.0))
        call = Call(lambda: link.requests.ping(timeout=3.0))
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

        assert link.requests.query("m", timeout=0.2) is None
        assert not link.is_connected
        (request,) = display.peers[0].read(1)
        assert isinstance(request, QueryRequest)
        with contextlib.suppress(OSError):  # the Hub hung up: a late reply has no road
            display.peers[0].send(QueryResponse(method="m", result={"late": True}))

        link.connect()
        link.start_listener()
        again = Call(lambda: link.requests.query("m", timeout=3.0))
        display.peers[1].read(1)
        display.peers[1].send(QueryResponse(method="m", result={"own": True}))

        assert again.wait()
        assert again.result == QueryResponse(method="m", result={"own": True})
        link.close()

    def test_a_ping_that_times_out_does_not_retire_its_dial(
        self, display: Display
    ) -> None:
        link = _linked(display)

        assert link.requests.ping(timeout=0.1) is None

        assert link.is_connected
        link.close()

    def test_a_scene_that_times_out_keeps_its_dial_and_its_late_ack_is_dropped(
        self, display: Display
    ) -> None:
        link = _linked(display, recv_timeout=0.2)

        assert link.requests.show("slow", []) is None
        assert link.is_connected
        late = Call(lambda: link.requests.show("next", []))
        display.peer.read(2)
        display.peer.send(AckMessage(scene_id="slow"), AckMessage(scene_id="next"))

        assert late.wait()
        assert late.result == AckMessage(scene_id="next")
        link.close()


class TestRequestLocks:
    def test_a_budget_spent_waiting_for_the_lock_sends_nothing_and_retires_nothing(
        self, display: Display
    ) -> None:
        link = _linked(display)
        first = Call(lambda: link.requests.ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        with pytest.raises(DisplayBusyError):
            link.requests.ping(timeout=0.1)

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
        slow = Call(lambda: link.requests.query("slow", timeout=3.0))
        (request,) = display.peer.read(1)
        assert isinstance(request, QueryRequest)

        probe = Call(lambda: link.requests.ping(timeout=3.0))
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
        call = Call(lambda: link.requests.ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        link.close()
        link.connect()
        link.start_listener()
        display.peers[1].send(PongMessage(ts=sent.ts))

        assert call.wait()
        assert isinstance(call.error, ConnectionClosedError)
        link.close()

    def test_without_a_listener_the_wait_fails_instead_of_reading_the_new_socket(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        call = Call(lambda: link.requests.ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        link.close()
        link.connect()
        display.peers[1].send(PongMessage(ts=sent.ts))

        assert call.wait()
        assert isinstance(call.error, ConnectionClosedError)
        link.close()


class TestAWriteThatRaises:
    def test_it_retires_its_dial_and_the_next_show_gets_its_own_ack(
        self, display: Display
    ) -> None:
        link = _linked(display)
        display.sockets[0].fail_next_send = True

        with pytest.raises(OSError, match="fell over"):
            link.requests.send_scene(_scene("lost"))
        assert not link.is_connected

        link.connect()
        link.start_listener()
        shown = Call(lambda: link.requests.show("next", []))
        display.peers[1].read(1)
        display.peers[1].send(AckMessage(scene_id="next"))

        assert shown.wait()
        assert shown.result == AckMessage(scene_id="next")
        link.close()


class TestAStoppedListenerEndsItsDial:
    def test_stopping_the_listener_closes_the_connection(
        self, display: Display
    ) -> None:
        link = _linked(display)

        link.stop_listener()

        assert not link.is_connected

    def test_a_reply_waiting_when_the_listener_stops_fails_at_once(
        self, display: Display
    ) -> None:
        link = _linked(display)
        call = Call(lambda: link.requests.ping(timeout=3.0))
        display.peer.read(1)

        link.stop_listener()

        assert call.wait(1.0)
        assert isinstance(call.error, ConnectionClosedError)


class TestOneSocketOneCallerAtATime:
    def test_a_read_and_a_write_of_two_request_kinds_never_overlap_on_the_socket(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        waiting = Call(lambda: link.requests.query("slow", timeout=3.0))
        (request,) = display.peer.read(1)
        assert isinstance(request, QueryRequest)

        probes = [Call(lambda: link.requests.ping(timeout=0.3)) for _ in range(3)]
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
        first = Call(lambda: link.requests.ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        with pytest.raises(DisplayBusyError):
            link.requests.ping(timeout=0.05)

        display.peer.send(PongMessage(ts=sent.ts))
        assert first.wait()
        link.close()

    def test_a_probe_that_finds_a_ping_in_flight_does_not_report_a_dead_display(
        self, display: Display
    ) -> None:
        link = _linked(display)
        first = Call(lambda: link.requests.ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        assert link.requests.probe_alive(0.05) is True

        assert display.peer.read(1, timeout=0.1) == []
        display.peer.send(PongMessage(ts=sent.ts))
        assert first.wait()
        link.close()

    def test_a_query_or_a_scene_that_lost_its_lock_wait_is_still_a_plain_timeout(
        self, display: Display
    ) -> None:
        link = _linked(display)
        slow = Call(lambda: link.requests.query("slow", timeout=3.0))
        display.peer.read(1)

        assert link.requests.query("other", timeout=0.05) is None
        assert link.is_connected

        link.close()
        assert slow.wait()


class TestOneReaderPerDial:
    def test_a_listener_started_during_an_inline_wait_waits_for_it(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        pinging = Call(lambda: link.requests.ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        starting = Call(link.start_listener)
        assert not starting.wait(0.3), (
            "the inline read holds the dial's one reader slot"
        )
        display.peer.send(PongMessage(ts=sent.ts))

        assert pinging.wait()
        assert starting.wait()
        assert link.listener_active
        assert display.sockets[0].reader_overlaps == 0
        link.close()

    def test_two_request_kinds_waiting_inline_share_one_reader_and_both_are_answered(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        querying = Call(lambda: link.requests.query("m", timeout=3.0))
        display.peer.read(1)
        pinging = Call(lambda: link.requests.ping(timeout=3.0))
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
        pinging = Call(lambda: link.requests.ping(timeout=3.0))
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
        pinging = Call(lambda: link.requests.ping(timeout=3.0))
        (sent,) = display.peer.read(1)
        assert isinstance(sent, PingMessage)

        display.peer.send(
            ObserverMessage(topic="t", payload={"n": 1}), PongMessage(ts=sent.ts)
        )

        assert pinging.wait()
        link.start_listener()
        assert link.events.poll_event(1.0).topic == "t"
        link.close()


class TestInlineReadingKeepsTheSocketLockShort:
    def test_a_ping_is_written_promptly_while_a_query_waits_inline_and_replies_stream(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        querying = Call(lambda: link.requests.query("slow", timeout=5.0))
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
            probe = Call(lambda: link.requests.ping(timeout=3.0))
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
        querying = Call(lambda: link.requests.query("slow", timeout=5.0))
        display.peer.read(1)

        probe = Call(lambda: link.requests.ping(timeout=3.0))
        (sent,) = display.peer.read(1, timeout=0.5)

        assert isinstance(sent, PingMessage), "the wait held the socket lock in select"
        display.peer.send(PongMessage(ts=sent.ts), QueryResponse(method="slow"))
        assert probe.wait()
        assert querying.wait()
        link.close()


class TestRacingWritersAreReleasedByRetirement:
    def test_a_show_and_a_send_scene_against_a_wedged_peer_are_both_released_by_close(
        self, display: Display
    ) -> None:
        link = _linked(display)
        big = ScenePresentation(frame_id="big").message(
            "big", [TextElement(id="t", content="x" * (8 * 1024 * 1024))]
        )
        replicating = Call(lambda: link.requests.send_scene(big))
        assert not replicating.wait(0.3), "the peer reads nothing: the write wedges"
        showing = Call(lambda: link.requests.show("next", []))
        assert not showing.wait(0.2), "the show waits behind the wedged writer"

        link.close()  # retire: shutdown wakes the sender and frees the socket lock

        assert replicating.wait(3.0)
        assert showing.wait(3.0)
        assert isinstance(replicating.error, OSError)


class TestEveryRetirementReachesTheRegistry:
    """Rule 9: whatever retires a dial, the registry redials and reconciles."""

    @staticmethod
    def _registry(display: Display) -> tuple[ClientRegistry, DisplayLink]:
        registry = ClientRegistry()
        link = DisplayLink(dialer=display, auto_spawn=False, recv_timeout=3.0)
        registry._client = link
        registry.get()
        return registry, link

    @staticmethod
    def _redialed(display: Display, registry: ClientRegistry) -> None:
        registry.get()
        assert display.dials == 2
        (first,) = display.peers[1].read(1)
        assert isinstance(first, HubManifestMessage)

    def test_a_reader_that_ends(self, display: Display) -> None:
        registry, link = self._registry(display)
        display.peers[0].close()
        assert until(lambda: not link.is_connected)

        self._redialed(display, registry)

        assert link.listener_active
        link.close()

    def test_a_query_that_times_out(self, display: Display) -> None:
        registry, link = self._registry(display)
        assert link.requests.query("m", timeout=0.1) is None

        self._redialed(display, registry)

        assert link.listener_active
        link.close()

    def test_a_torn_write(self, display: Display) -> None:
        registry, link = self._registry(display)
        display.sockets[0].fail_next_send = True
        with pytest.raises(OSError, match="fell over"):
            link.requests.send_scene(_scene("s"))

        self._redialed(display, registry)

        assert link.listener_active
        link.close()


class TestAPeerThatStopsReading:
    def test_the_wedged_writer_ends_within_the_send_bound_and_releases_the_queue(
        self, display: Display
    ) -> None:
        link = _linked(display)
        big = ScenePresentation(frame_id="big").message(
            "big", [TextElement(id="t", content="x" * (8 * 1024 * 1024))]
        )
        began = time.monotonic()
        replicating = Call(lambda: link.requests.send_scene(big))
        showing = Call(lambda: link.requests.show("next", []))
        pinging = Call(lambda: link.requests.ping(timeout=5.0))

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
        link = DisplayLink(dialer=display, auto_spawn=False, recv_timeout=3.0)
        registry._client = link
        registry.get()

        def forbidden() -> None:
            pytest.fail("the retire went through ClientRegistry.drop() under a lock")

        monkeypatch.setattr(registry, "drop", forbidden)

        assert link.requests.query("m", timeout=0.1) is None
        assert not link.is_connected
        link.close()

    def test_no_module_of_the_dial_model_names_the_registry_or_the_store(self) -> None:
        # The registry lock and the store lock sit above the model's locks; a
        # module that holds the model's locks must never reach for either.
        hub = (
            Path(__file__).resolve().parents[2] / "src" / "punt_lux" / "domain" / "hub"
        )
        modelled = (
            "dial_generation",
            "dial_reader",
            "display_connection",
            "display_listener",
            "display_replies",
            "display_requests",
            "listener_thread",
            "reply_sink",
        )
        forbidden = ("ClientRegistry", "client_registry", "hub_display", "HubDisplay")

        offenders = [
            f"{name}: {word}"
            for name in modelled
            for word in forbidden
            if word in (hub / f"{name}.py").read_text(encoding="utf-8")
        ]

        assert offenders == []


class TestConnectCoordinatesTheDialAndItsListener:
    def test_connect_with_listen_starts_the_reader_on_the_new_dial(
        self, display: Display
    ) -> None:
        link = DisplayLink(dialer=display, auto_spawn=False, recv_timeout=3.0)

        link.connect(listen=True)

        assert link.listener_active
        link.close()

    def test_connect_alone_starts_no_reader(self, display: Display) -> None:
        link = DisplayLink(dialer=display, auto_spawn=False, recv_timeout=3.0)

        link.connect()

        assert not link.listener_active
        link.close()
