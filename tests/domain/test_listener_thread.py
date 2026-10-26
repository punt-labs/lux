"""ListenerThread -- the background reader that lives and dies with its dial."""

from __future__ import annotations

import base64
import logging
import pickle
import struct
import threading
import time
from typing import TYPE_CHECKING, final

import pytest

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.dial_generation import DialGeneration
from punt_lux.domain.hub.dial_reader import DialReader
from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.domain.hub.inbound_router import InboundRouter
from punt_lux.domain.hub.interaction_handlers import InteractionHandlers
from punt_lux.domain.hub.listener_thread import ListenerThread
from punt_lux.protocol import (
    HEADER_FORMAT,
    AckMessage,
    ObserverMessage,
    PongMessage,
    SceneMessage,
    encode_frame,
    encode_message,
)
from tests.domain.display_double import Display, until
from tests.link_access import no_reader, reading_of

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.settlement import Settlement
    from punt_lux.protocol import Message


@final
class _Rig:
    """A connection to a scripted display, and a listener over it that records."""

    display: Display
    connection: DisplayConnection
    routed: list[Message]
    listener: ListenerThread

    def __init__(
        self, route: Callable[[DialGeneration, Message], None] | None = None
    ) -> None:
        self.display = Display()
        self.connection = DisplayConnection(self.display, 1.0, settle_unread=no_reader)
        self.connection.open()
        self.routed = []
        self.listener = ListenerThread(self.connection, route or self._record)

    def _record(self, _generation: DialGeneration, msg: Message) -> None:
        self.routed.append(msg)

    def close(self) -> None:
        self.listener.stop()
        self.connection.close()
        self.display.close()


@pytest.fixture
def rig() -> Iterator[_Rig]:
    made = _Rig()
    yield made
    made.close()


def _pong(ts: float) -> bytes:
    return encode_message(PongMessage(ts=ts))


def _event(topic: str = "t") -> bytes:
    return encode_message(ObserverMessage(topic=topic, payload={}))


class TestRouting:
    def test_every_decoded_message_is_routed(self, rig: _Rig) -> None:
        rig.listener.start()
        rig.display.peer.send_raw(_pong(1.0) + _pong(2.0))

        assert until(lambda: len(rig.routed) == 2)
        assert rig.routed == [PongMessage(ts=1.0), PongMessage(ts=2.0)]

    def test_a_frame_split_across_reads_is_routed_once_complete(
        self, rig: _Rig
    ) -> None:
        rig.listener.start()
        wire = _pong(3.0)
        rig.display.peer.send_raw(wire[:3])
        time.sleep(0.2)
        assert rig.routed == []

        rig.display.peer.send_raw(wire[3:])

        assert until(lambda: rig.routed == [PongMessage(ts=3.0)])

    def test_a_message_is_routed_with_the_generation_it_was_read_from(self) -> None:
        seen: list[DialGeneration] = []
        made = _Rig(lambda generation, _msg: seen.append(generation))
        try:
            expected = made.connection.require()
            made.listener.start()
            made.display.peer.send_raw(_pong(1.0))

            assert until(lambda: bool(seen))
            assert seen == [expected]
        finally:
            made.close()


class TestLifecycle:
    def test_a_new_listener_has_not_started(self, rig: _Rig) -> None:
        assert (rig.listener.started, rig.listener.alive) == (False, False)

    def test_start_is_idempotent_while_running(self, rig: _Rig) -> None:
        rig.listener.start()
        threads = {t for t in threading.enumerate() if t.name == "lux-listener"}

        rig.listener.start()

        assert {t for t in threading.enumerate() if t.name == "lux-listener"} == threads
        assert rig.listener.alive

    def test_stop_joins_the_thread_and_forgets_it(self, rig: _Rig) -> None:
        rig.listener.start()

        rig.listener.stop()

        assert (rig.listener.started, rig.listener.alive) == (False, False)

    def test_stopping_a_listener_never_started_is_not_an_error(self, rig: _Rig) -> None:
        rig.listener.stop()

        assert rig.connection.is_open

    def test_starting_with_no_connection_raises(self) -> None:
        listener = ListenerThread(
            DisplayConnection(Display(), 1.0, settle_unread=no_reader),
            lambda _g, _m: None,
        )

        with pytest.raises(DisplayNotConnectedError):
            listener.start()

    def test_exits_when_the_display_closes_the_connection(self, rig: _Rig) -> None:
        rig.listener.start()
        rig.display.peer.close()

        assert until(lambda: not rig.listener.alive)
        assert rig.listener.started  # exited, but was started: the caller can tell

    def test_exits_when_the_connection_is_closed_under_it(self, rig: _Rig) -> None:
        rig.listener.start()

        rig.connection.close()

        assert until(lambda: not rig.listener.alive)

    def test_is_current_only_on_the_listener_thread(self) -> None:
        seen: list[bool] = []
        holder: list[ListenerThread] = []
        made = _Rig(lambda _g, _m: seen.append(holder[0].is_current))
        holder.append(made.listener)
        try:
            made.listener.start()
            made.display.peer.send_raw(_pong(1.0))

            assert until(lambda: bool(seen))
            assert seen == [True]
            assert made.listener.is_current is False
        finally:
            made.close()


class TestAReaderLivesAndDiesWithItsDial:
    def test_stopping_retires_the_dial_so_a_restart_needs_a_new_one(
        self, rig: _Rig
    ) -> None:
        rig.listener.start()
        rig.listener.stop()

        assert not rig.connection.is_open
        with pytest.raises(ConnectionClosedError):
            rig.listener.start()

        rig.connection.open()
        rig.listener.start()
        assert rig.listener.alive

    def test_a_reader_that_ends_on_its_own_retires_its_dial(self, rig: _Rig) -> None:
        generation = rig.connection.require()
        rig.listener.start()

        rig.display.peer.close()

        assert until(lambda: not rig.connection.is_open)
        assert generation.is_closed

    def test_a_dial_has_one_reader_even_if_the_slot_is_claimed_elsewhere(
        self, rig: _Rig
    ) -> None:
        assert reading_of(rig.connection).claim_for_listener()

        rig.listener.start()

        assert not rig.listener.alive

    def test_a_reply_unrouted_when_the_listener_stops_skews_no_later_request(
        self, rig: _Rig
    ) -> None:
        entered = threading.Event()
        release = threading.Event()
        router = InboundRouter(InteractionHandlers())

        def route(generation: DialGeneration, msg: Message) -> None:
            if isinstance(msg, ObserverMessage):
                entered.set()
                release.wait(timeout=5)
            router.route(generation, msg)

        made = _Rig(route)
        try:
            old = made.connection.require()
            old.send_scene(_scene("s"))
            made.listener.start()
            made.display.peer.send_raw(_event() + encode_message(_ack("s")))
            assert entered.wait(3)

            made.listener.stop()
            made.connection.open()
            fresh = made.connection.require()
            fresh.send_scene(_scene("t"))
            release.set()

            assert until(lambda: not made.listener.alive)
            assert fresh.owed_acks == 1  # the old dial's ack did not settle this one
            fresh.deliver(_ack("t"))
            assert fresh.owed_acks == 0
        finally:
            release.set()
            made.close()


def _ack(scene_id: str) -> Message:
    return AckMessage(scene_id=scene_id)


def _scene(scene_id: str) -> SceneMessage:
    return SceneMessage(id=scene_id, elements=[], frame_id=scene_id)


class _Stalled:
    """A reader held inside its route, so a test can stop and redial around it."""

    entered: threading.Event
    release: threading.Event
    routed: list[tuple[DialGeneration, Message]]

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.routed = []
        self._router = InboundRouter(InteractionHandlers())

    def route(self, generation: DialGeneration, msg: Message) -> None:
        if not self.entered.is_set():
            self.entered.set()
            self.release.wait(timeout=5)
        self.routed.append((generation, msg))
        self._router.route(generation, msg)


def _stalled_rig(monkeypatch: pytest.MonkeyPatch) -> tuple[_Rig, _Stalled]:
    monkeypatch.setattr("punt_lux.domain.hub.listener_thread._JOIN_TIMEOUT", 0.1)
    stalled = _Stalled()
    return _Rig(stalled.route), stalled


class TestAStoppedReaderIsConfinedToItsOwnGeneration:
    def test_the_step_a_stopped_reader_still_takes_lands_in_its_own_sink_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        made, stalled = _stalled_rig(monkeypatch)
        try:
            old = made.connection.require()
            made.listener.start()
            made.display.peer.send_raw(_pong(1.0))
            assert stalled.entered.wait(3)

            made.listener.stop()  # cannot join: the reader is inside its route
            assert made.listener.alive
            made.connection.open()
            fresh = made.connection.require()
            waiting = fresh.send_ping(1.0)
            stalled.release.set()

            assert until(lambda: not made.listener.alive)
            assert stalled.routed[0][0] is old
            assert not fresh.answered(waiting)  # the new dial's waiter was not answered
            assert made.connection.require() is fresh
        finally:
            stalled.release.set()
            made.close()

    def test_the_new_dial_s_waiter_is_never_answered_by_the_old_dial_s_reply(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        made, stalled = _stalled_rig(monkeypatch)
        try:
            made.listener.start()
            made.display.peer.send_raw(_pong(7.0))
            assert stalled.entered.wait(3)
            made.listener.stop()
            made.connection.open()
            fresh = made.connection.require()
            waiting = fresh.send_ping(7.0)
            stalled.release.set()
            assert until(lambda: not made.listener.alive)

            assert fresh.await_reply(waiting, 0.2) is None
        finally:
            stalled.release.set()
            made.close()

    def test_a_message_after_the_one_a_stopped_reader_held_is_not_routed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        made, stalled = _stalled_rig(monkeypatch)
        try:
            made.listener.start()
            made.display.peer.send_raw(_pong(1.0) + _pong(2.0) + _pong(3.0))
            assert stalled.entered.wait(3)
            made.listener.stop()
            made.connection.open()
            made.listener.start()  # the successor, on the new dial
            stalled.release.set()
            assert until(lambda: len(stalled.routed) >= 1)
            time.sleep(0.3)

            routed_ts = [m.ts for _g, m in stalled.routed if isinstance(m, PongMessage)]
            assert routed_ts == [1.0]
        finally:
            stalled.release.set()
            made.close()

    def test_a_read_that_fails_on_a_retired_dial_reports_nothing_and_closes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        made, stalled = _stalled_rig(monkeypatch)
        try:
            made.listener.start()
            made.display.peer.send_raw(_pong(1.0))
            assert stalled.entered.wait(3)
            made.listener.stop()
            made.connection.open()
            replacement = made.connection.require()
            caplog.clear()
            with caplog.at_level(logging.DEBUG):
                stalled.release.set()
                assert until(lambda: not made.listener.alive)

            assert made.connection.require() is replacement
            assert not replacement.is_closed
            assert not [r for r in caplog.records if r.levelno >= logging.INFO]
        finally:
            stalled.release.set()
            made.close()

    def test_a_malformed_frame_in_a_retired_reader_s_buffer_closes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        made, stalled = _stalled_rig(monkeypatch)
        try:
            made.listener.start()
            bad = b"{not json"
            made.display.peer.send_raw(
                _pong(1.0) + struct.pack(HEADER_FORMAT, len(bad)) + bad
            )
            assert stalled.entered.wait(3)
            made.listener.stop()
            made.connection.open()
            replacement = made.connection.require()
            caplog.clear()
            with caplog.at_level(logging.DEBUG):
                stalled.release.set()
                assert until(lambda: not made.listener.alive)

            assert not replacement.is_closed
            assert made.connection.is_open
            assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
        finally:
            stalled.release.set()
            made.close()

    def test_an_abandoned_reader_never_reads_the_replacement_s_socket(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        made, stalled = _stalled_rig(monkeypatch)
        try:
            made.listener.start()
            made.display.peer.send_raw(_pong(1.0))
            assert stalled.entered.wait(3)
            made.listener.stop()
            made.connection.open()
            replacement = made.connection.require()
            made.display.peer.send_raw(_pong(9.0))
            stalled.release.set()
            assert until(lambda: not made.listener.alive)

            assert replacement.poll_chunk(1.0) == _pong(9.0)
        finally:
            stalled.release.set()
            made.close()

    def test_a_waiter_on_the_new_dial_fails_promptly_while_an_abandoned_reader_lives(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        made, stalled = _stalled_rig(monkeypatch)
        try:
            made.listener.start()
            made.display.peer.send_raw(_pong(1.0))
            assert stalled.entered.wait(3)
            made.listener.stop()
            made.connection.open()
            made.listener.start()
            fresh = made.connection.require()
            waiting = fresh.send_ping(1.0)
            assert made.listener.alive

            made.display.peer.close()  # the new dial's display goes away

            with pytest.raises(ConnectionClosedError):
                fresh.await_reply(waiting, 3.0)
        finally:
            stalled.release.set()
            made.close()


class TestAStaleReportCannotTouchTheReplacement:
    def test_a_report_for_a_replaced_dial_leaves_the_replacement_and_its_waiter(
        self, rig: _Rig
    ) -> None:
        stale = rig.connection.require()
        rig.connection.close()
        rig.connection.open()
        fresh = rig.connection.require()
        waiting = fresh.send_ping(1.0)
        answered: list[object] = []
        waiter = threading.Thread(
            target=lambda: answered.append(fresh.await_reply(waiting, 3.0))
        )
        waiter.start()

        assert rig.connection.close_if_current(stale, cause="hub") is False
        fresh.deliver(PongMessage(ts=1.0))
        waiter.join(3.0)

        assert answered == [PongMessage(ts=1.0)]
        assert rig.connection.is_open

    def test_a_report_and_a_redial_cannot_interleave_between_its_check_and_its_act(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The report decides and acts in one step under the state lock. Pause it
        # between the two (inside ``mark_closed``) and start a redial: the redial
        # must wait for the lock, so the dial it publishes is never the one the
        # report closes.
        display = Display()
        connection = DisplayConnection(display, 1.0, settle_unread=no_reader)
        connection.open()
        old = connection.require()
        redial_started = threading.Event()
        redial_done = threading.Event()

        def redial() -> None:
            redial_started.set()
            connection.close()
            connection.open()
            redial_done.set()

        redialer = threading.Thread(target=redial)
        real_mark_closed = DialGeneration.mark_closed

        def paused_mark_closed(
            generation: DialGeneration, cause: RetireCause
        ) -> Settlement:
            if generation is old:
                redialer.start()
                assert redial_started.wait(3.0)
                assert not redial_done.wait(0.3), "the redial ran between check and act"
            return real_mark_closed(generation, cause)

        monkeypatch.setattr(DialGeneration, "mark_closed", paused_mark_closed)
        try:
            assert connection.close_if_current(old, cause="hub") is True
            redialer.join(3.0)

            assert redial_done.is_set()
            assert connection.is_open
            assert not connection.require().is_closed
        finally:
            connection.close()
            display.close()


class TestAFailedThreadStart:
    def test_a_thread_that_cannot_start_does_not_leave_a_phantom_reader(
        self, rig: _Rig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(_thread: threading.Thread) -> None:
            raise RuntimeError("can't start new thread")

        monkeypatch.setattr(threading.Thread, "start", refuse)

        with pytest.raises(RuntimeError, match="can't start"):
            rig.listener.start()

        assert not rig.connection.has_reader
        assert not rig.listener.started
        assert reading_of(rig.connection).claim_for_listener()  # the slot is free again


class TestTheRunIsPublishedBeforeTheThreadCanUseIt:
    def test_a_route_that_fires_as_the_thread_starts_knows_it_is_the_listener(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[bool] = []
        real_start = threading.Thread.start

        def start_then_let_it_run(thread: threading.Thread) -> None:
            real_start(thread)
            time.sleep(0.3)  # the reader runs before ``start`` returns to its caller

        holder: list[_Rig] = []
        made = _Rig(lambda _g, _m: seen.append(holder[0].listener.is_current))
        holder.append(made)
        try:
            made.display.peer.send_raw(_pong(1.0))
            monkeypatch.setattr(threading.Thread, "start", start_then_let_it_run)

            made.listener.start()

            assert until(lambda: bool(seen))
            assert seen == [True], "the listener thread did not know itself"
        finally:
            monkeypatch.undo()
            made.close()

    def test_a_stop_while_the_thread_is_starting_finds_the_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_start = threading.Thread.start
        holder: list[_Rig] = []
        stopped: list[bool] = []

        def start_then_stop(thread: threading.Thread) -> None:
            real_start(thread)
            holder[0].listener.stop()  # arrives inside the start window
            stopped.append(not holder[0].connection.is_open)

        made = _Rig()
        holder.append(made)
        try:
            monkeypatch.setattr(threading.Thread, "start", start_then_stop)

            made.listener.start()

            assert stopped == [True], "stop() did not see the run and retire its dial"
        finally:
            monkeypatch.undo()
            made.close()


class TestForeignMessages:
    def test_a_scene_from_a_display_closes_the_connection_and_unpickles_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        rig: _Rig,
    ) -> None:
        unpickled: list[bytes] = []
        monkeypatch.setattr(pickle, "loads", unpickled.append)
        payload = base64.b64encode(b"not really a pickle").decode("ascii")
        with caplog.at_level(logging.ERROR):
            rig.listener.start()
            rig.display.peer.send_raw(
                encode_frame(
                    {
                        "type": "scene",
                        "id": "s",
                        "frame_id": "f",
                        "elements": [{"_pickled": payload}],
                    }
                )
            )
            assert until(lambda: not rig.connection.is_open)

        assert unpickled == []
        assert rig.routed == []
        assert any(
            r.levelno == logging.ERROR and "scene" in r.getMessage()
            for r in caplog.records
        )


class TestMalformedFrames:
    def test_a_deeply_nested_frame_closes_the_connection_and_is_logged(
        self, caplog: pytest.LogCaptureFixture, rig: _Rig
    ) -> None:
        depth = 200_000
        bomb = b"[" * depth + b"]" * depth
        with caplog.at_level(logging.ERROR):
            rig.listener.start()
            rig.display.peer.send_raw(struct.pack(HEADER_FORMAT, len(bomb)) + bomb)
            assert until(lambda: not rig.connection.is_open)

        assert rig.routed == []
        assert any("malformed frame" in r.getMessage() for r in caplog.records)

    def test_any_decoder_failure_is_a_malformed_frame_not_a_dead_thread(
        self, monkeypatch: pytest.MonkeyPatch, rig: _Rig
    ) -> None:
        def explode(_raw: dict[str, object]) -> Message:
            raise IndexError("a decoder bug")

        monkeypatch.setattr("punt_lux.protocol.message_from_dict", explode)
        rig.listener.start()
        rig.display.peer.send_raw(_pong(1.0))

        assert until(lambda: not rig.connection.is_open)
        assert rig.routed == []

    def test_messages_decoded_before_a_bad_frame_are_still_routed(
        self, rig: _Rig
    ) -> None:
        rig.listener.start()
        bad = b"{not json"
        rig.display.peer.send_raw(
            _pong(1.0) + struct.pack(HEADER_FORMAT, len(bad)) + bad
        )

        assert until(lambda: not rig.listener.alive)
        assert rig.routed == [PongMessage(ts=1.0)]

    def test_the_failure_is_logged_with_the_display_and_the_frames_first_bytes(
        self, caplog: pytest.LogCaptureFixture, rig: _Rig
    ) -> None:
        with caplog.at_level(logging.ERROR):
            rig.listener.start()
            bad = b"{not json"
            rig.display.peer.send_raw(struct.pack(HEADER_FORMAT, len(bad)) + bad)
            assert until(lambda: not rig.listener.alive)

        (record,) = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert "pair-1" in record.getMessage()
        assert "not json" in record.getMessage()

    def test_the_connection_is_closed_so_a_reconnect_starts_on_a_boundary(
        self, rig: _Rig
    ) -> None:
        rig.listener.start()
        bad = b"[1, 2]"
        rig.display.peer.send_raw(struct.pack(HEADER_FORMAT, len(bad)) + bad)

        assert until(lambda: not rig.connection.is_open)

    def test_a_frame_that_decodes_to_no_message_is_a_malformed_frame_too(
        self, rig: _Rig
    ) -> None:
        rig.listener.start()
        rig.display.peer.send_raw(encode_frame({"type": "ack"}))

        assert until(lambda: not rig.listener.alive)
        assert rig.routed == []
        assert not rig.connection.is_open

    def test_a_clean_close_is_logged_at_info(
        self, caplog: pytest.LogCaptureFixture, rig: _Rig
    ) -> None:
        with caplog.at_level(logging.INFO):
            rig.listener.start()
            rig.display.peer.close()
            assert until(lambda: not rig.listener.alive)

        assert any(
            r.levelno == logging.INFO and "closed the connection" in r.getMessage()
            for r in caplog.records
        )


class TestAbandonedThread:
    def test_start_after_a_stop_that_could_not_join_runs_a_new_reader_on_a_new_dial(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        made, stalled = _stalled_rig(monkeypatch)
        try:
            made.listener.start()
            made.display.peer.send_raw(_pong(1.0))
            assert stalled.entered.wait(3)
            made.listener.stop()
            assert made.listener.alive  # stuck in its handler, told to stop

            with pytest.raises(ConnectionClosedError):
                made.listener.start()  # its dial is retired: redial first
            made.connection.open()
            with caplog.at_level(logging.ERROR):
                made.listener.start()
            stalled.release.set()
            made.display.peer.send_raw(_pong(2.0))

            assert until(lambda: PongMessage(ts=2.0) in [m for _g, m in stalled.routed])
            assert "Abandoning" in caplog.text
        finally:
            stalled.release.set()
            made.close()

    def test_start_while_running_and_not_stopping_changes_nothing(
        self, rig: _Rig
    ) -> None:
        rig.listener.start()
        threads = {t for t in threading.enumerate() if t.name == "lux-listener"}

        rig.listener.start()

        assert {t for t in threading.enumerate() if t.name == "lux-listener"} == threads


class TestARaisingRoute:
    def test_a_business_event_whose_handler_raises_costs_its_message_not_the_listener(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        routed: list[Message] = []

        def route(_g: DialGeneration, msg: Message) -> None:
            if msg == ObserverMessage(topic="boom", payload={}):
                raise RuntimeError("the handler blew up")
            routed.append(msg)

        made = _Rig(route)
        try:
            with caplog.at_level(logging.ERROR):
                made.listener.start()
                made.display.peer.send_raw(_event("boom") + _event("after"))
                assert until(
                    lambda: routed == [ObserverMessage(topic="after", payload={})]
                )

            assert made.listener.alive
            assert made.connection.is_open
            (record,) = [r for r in caplog.records if r.levelno == logging.ERROR]
            assert "ObserverMessage" in record.getMessage()
            assert "pair-1" in record.getMessage()
        finally:
            made.close()

    def test_a_reply_whose_routing_raises_is_not_skipped_it_ends_the_dial(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        routed: list[Message] = []

        def route(_g: DialGeneration, msg: Message) -> None:
            if msg == PongMessage(ts=1.0):
                raise RuntimeError("the sink blew up")
            routed.append(msg)

        made = _Rig(route)
        try:
            with caplog.at_level(logging.ERROR):
                made.listener.start()
                made.display.peer.send_raw(_pong(1.0) + _pong(2.0))
                assert until(lambda: not made.connection.is_open)

            assert until(lambda: not made.listener.alive)
            assert routed == []  # the reply after the failed one is not routed either
        finally:
            made.close()

    def test_a_failed_route_logs_a_bounded_repr_of_the_message(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def route(_g: DialGeneration, _msg: Message) -> None:
            raise RuntimeError("no")

        made = _Rig(route)
        try:
            with caplog.at_level(logging.ERROR):
                made.listener.start()
                made.display.peer.send_raw(_event("ts-marker"))
                assert until(lambda: bool(caplog.records))

            assert "ts-marker" in caplog.text
        finally:
            made.close()


class TestReportingTheEnd:
    def test_a_display_that_closes_the_stream_retires_the_dial(self, rig: _Rig) -> None:
        generation = rig.connection.require()
        rig.listener.start()

        rig.display.peer.close()

        assert until(lambda: generation.is_closed)
        assert until(lambda: not rig.connection.is_open)

    def test_a_read_failure_on_an_open_dial_is_a_warning_and_retires_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        rig: _Rig,
    ) -> None:
        def fails(_generation: DialGeneration, _timeout: float) -> bytes | None:
            raise OSError("the socket fell over")

        monkeypatch.setattr(DialGeneration, "poll_chunk", fails)
        with caplog.at_level(logging.WARNING):
            rig.listener.start()
            assert until(lambda: not rig.connection.is_open)

        warned = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("pair-1" in r.getMessage() for r in warned)

    def test_a_deliberate_close_is_debug_and_not_a_break(
        self, caplog: pytest.LogCaptureFixture, rig: _Rig
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            rig.listener.start()
            rig.connection.close()
            assert until(lambda: not rig.listener.alive)

        assert not [r for r in caplog.records if r.levelno >= logging.INFO]


class TestABornClaimedDialReplacedInTheGap:
    def test_start_for_a_replaced_dial_starts_nothing_on_its_replacement(self) -> None:
        display = Display()
        connection = DisplayConnection(display, 1.0, settle_unread=no_reader)
        listener = ListenerThread(connection, lambda _g, _m: None)
        try:
            born = connection.open_listening()
            assert born is not None
            connection.close()  # retired in the gap ...
            connection.open()  # ... and replaced by a dial with no reader

            with pytest.raises(ConnectionClosedError):
                listener.start_on(born)

            assert not listener.alive
            assert not connection.has_reader
        finally:
            connection.close()
            display.close()


class TestTheReaderLoopStopsOnItsDialsRetirement:
    """The loop ends on ``generation.is_closed``, not only on its stopping flag."""

    def test_a_reader_started_on_a_retired_dial_reads_and_routes_nothing(
        self, rig: _Rig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        generation = rig.connection.require()
        reads: list[float] = []

        def spy(self: DialGeneration, timeout: float) -> bytes | None:
            reads.append(timeout)
            msg = "read after the retirement"
            raise ConnectionClosedError(msg)

        monkeypatch.setattr(DialGeneration, "poll_chunk", spy)
        generation.mark_closed("hub")  # retired; its stopping flag was never set
        rig.display.peer.send_raw(_pong(1.0))
        reader = DialReader(rig.connection, generation, rig._record, threading.Event())

        reader.run()

        assert reads == [], "the loop read a dial that was already retired"
        assert rig.routed == []
