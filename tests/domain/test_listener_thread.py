"""ListenerThread -- the background reader over the display connection."""

from __future__ import annotations

import base64
import logging
import pickle
import socket
import struct
import threading
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.handshake_outcome import HandshakeResult
from punt_lux.domain.hub.listener_thread import ListenerThread
from punt_lux.protocol import (
    HEADER_FORMAT,
    PongMessage,
    ReadyMessage,
    encode_frame,
    encode_message,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

    from punt_lux.protocol import Message


@final
class _PairDialer:
    """Hands out one end of a socket pair; the test drives the other."""

    peer: socket.socket | None

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.peer = None
        return self

    def dial(self, connect_timeout: float) -> HandshakeResult:
        ours, self.peer = socket.socketpair()
        return HandshakeResult(sock=ours, endpoint="pair", ready=ReadyMessage())


def _until(condition: Callable[[], bool], timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def _listening() -> tuple[
    ListenerThread, DisplayConnection, _PairDialer, list[Message]
]:
    dialer = _PairDialer()
    connection = DisplayConnection(dialer, 1.0)
    connection.open()
    routed: list[Message] = []
    listener = ListenerThread(connection, routed.append, connection.close)
    return listener, connection, dialer, routed


class TestRouting:
    def test_every_decoded_message_is_routed(self) -> None:
        listener, connection, dialer, routed = _listening()
        listener.start()
        try:
            assert dialer.peer is not None
            dialer.peer.sendall(encode_message(PongMessage(ts=1.0)))
            dialer.peer.sendall(encode_message(PongMessage(ts=2.0)))
            assert _until(lambda: len(routed) == 2)
            assert routed == [PongMessage(ts=1.0), PongMessage(ts=2.0)]
        finally:
            listener.stop()
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_a_frame_split_across_reads_is_routed_once_complete(self) -> None:
        listener, connection, dialer, routed = _listening()
        listener.start()
        try:
            assert dialer.peer is not None
            wire = encode_message(PongMessage(ts=3.0))
            dialer.peer.sendall(wire[:3])
            time.sleep(0.2)
            assert routed == []
            dialer.peer.sendall(wire[3:])
            assert _until(lambda: routed == [PongMessage(ts=3.0)])
        finally:
            listener.stop()
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()


class TestLifecycle:
    def test_a_new_listener_has_not_started(self) -> None:
        listener, connection, dialer, _ = _listening()
        try:
            assert (listener.started, listener.alive) == (False, False)
        finally:
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_start_is_idempotent_while_running(self) -> None:
        listener, connection, dialer, _ = _listening()
        try:
            listener.start()
            threads = {t for t in threading.enumerate() if t.name == "lux-listener"}
            listener.start()
            assert {
                t for t in threading.enumerate() if t.name == "lux-listener"
            } == threads
            assert listener.alive
        finally:
            listener.stop()
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_stop_joins_the_thread_and_forgets_it(self) -> None:
        listener, connection, dialer, _ = _listening()
        try:
            listener.start()
            listener.stop()
            assert (listener.started, listener.alive) == (False, False)
        finally:
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_stopping_a_listener_never_started_is_not_an_error(self) -> None:
        listener, connection, dialer, _ = _listening()
        try:
            listener.stop()
        finally:
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_exits_when_the_display_closes_the_connection(self) -> None:
        listener, connection, dialer, _ = _listening()
        try:
            listener.start()
            assert dialer.peer is not None
            dialer.peer.close()
            assert _until(lambda: not listener.alive)
            assert listener.started  # exited, but was started: the caller can tell
        finally:
            listener.stop()
            connection.close()

    def test_exits_when_the_connection_is_closed_under_it(self) -> None:
        listener, connection, dialer, _ = _listening()
        listener.start()
        connection.close()
        try:
            assert _until(lambda: not listener.alive)
        finally:
            listener.stop()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_is_current_only_on_the_listener_thread(self) -> None:
        seen: list[bool] = []
        dialer = _PairDialer()
        connection = DisplayConnection(dialer, 1.0)
        connection.open()
        holder: list[ListenerThread] = []

        def route(_msg: Message) -> None:
            seen.append(holder[0].is_current)

        listener = ListenerThread(connection, route, connection.close)
        holder.append(listener)
        listener.start()
        try:
            assert dialer.peer is not None
            dialer.peer.sendall(encode_message(PongMessage()))
            assert _until(lambda: bool(seen))
            assert seen == [True]
            assert listener.is_current is False
        finally:
            listener.stop()
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()


def _closed(peer: socket.socket | None, connection: DisplayConnection) -> None:
    connection.close()
    if peer is not None:
        peer.close()


class TestForeignMessages:
    def test_a_scene_from_a_display_closes_the_connection_and_unpickles_nothing(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        unpickled: list[bytes] = []

        def spy(data: bytes) -> None:
            unpickled.append(data)

        monkeypatch.setattr(pickle, "loads", spy)
        listener, connection, dialer, routed = _listening()
        payload = base64.b64encode(b"not really a pickle").decode("ascii")
        with caplog.at_level(logging.ERROR):
            listener.start()
            assert dialer.peer is not None
            dialer.peer.sendall(
                encode_frame(
                    {
                        "type": "scene",
                        "id": "s",
                        "frame_id": "f",
                        "elements": [{"_pickled": payload}],
                    }
                )
            )
            assert _until(lambda: not connection.is_open)
        try:
            assert unpickled == []
            assert routed == []
            assert any(
                r.levelno == logging.ERROR and "scene" in r.getMessage()
                for r in caplog.records
            )
        finally:
            listener.stop()
            _closed(dialer.peer, connection)


class TestMalformedFrames:
    def test_a_deeply_nested_frame_closes_the_connection_and_is_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        listener, connection, dialer, routed = _listening()
        depth = 200_000
        bomb = b"[" * depth + b"]" * depth
        with caplog.at_level(logging.ERROR):
            listener.start()
            assert dialer.peer is not None
            dialer.peer.sendall(struct.pack(HEADER_FORMAT, len(bomb)) + bomb)
            assert _until(lambda: not connection.is_open)
        try:
            assert routed == []
            assert any("malformed frame" in r.getMessage() for r in caplog.records)
        finally:
            listener.stop()
            _closed(dialer.peer, connection)

    def test_any_decoder_failure_is_a_malformed_frame_not_a_dead_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(_raw: dict[str, object]) -> Message:
            raise IndexError("a decoder bug")

        monkeypatch.setattr("punt_lux.protocol.message_from_dict", explode)
        listener, connection, dialer, routed = _listening()
        listener.start()
        try:
            assert dialer.peer is not None
            dialer.peer.sendall(encode_message(PongMessage(ts=1.0)))
            assert _until(lambda: not connection.is_open)
            assert routed == []
        finally:
            listener.stop()
            _closed(dialer.peer, connection)

    def test_messages_decoded_before_a_bad_frame_are_still_routed(self) -> None:
        listener, connection, dialer, routed = _listening()
        listener.start()
        try:
            assert dialer.peer is not None
            bad = b"{not json"
            dialer.peer.sendall(
                encode_message(PongMessage(ts=1.0))
                + struct.pack(HEADER_FORMAT, len(bad))
                + bad
            )
            assert _until(lambda: not listener.alive)
            assert routed == [PongMessage(ts=1.0)]
        finally:
            listener.stop()
            _closed(dialer.peer, connection)

    def test_the_failure_is_logged_with_the_display_and_the_frames_first_bytes(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        listener, connection, dialer, _ = _listening()
        with caplog.at_level(logging.ERROR):
            listener.start()
            assert dialer.peer is not None
            bad = b"{not json"
            dialer.peer.sendall(struct.pack(HEADER_FORMAT, len(bad)) + bad)
            assert _until(lambda: not listener.alive)
        try:
            (record,) = [r for r in caplog.records if r.levelno == logging.ERROR]
            assert "pair" in record.getMessage()
            assert "not json" in record.getMessage()
        finally:
            listener.stop()
            _closed(dialer.peer, connection)

    def test_the_connection_is_closed_so_a_reconnect_starts_on_a_boundary(
        self,
    ) -> None:
        listener, connection, dialer, _ = _listening()
        listener.start()
        try:
            assert dialer.peer is not None
            bad = b"[1, 2]"
            dialer.peer.sendall(struct.pack(HEADER_FORMAT, len(bad)) + bad)
            assert _until(lambda: not connection.is_open)
        finally:
            listener.stop()
            _closed(dialer.peer, connection)

    def test_a_frame_that_decodes_to_no_message_is_a_malformed_frame_too(self) -> None:
        listener, connection, dialer, routed = _listening()
        listener.start()
        try:
            assert dialer.peer is not None
            dialer.peer.sendall(encode_frame({"type": "ack"}))
            assert _until(lambda: not listener.alive)
            assert routed == []
            assert not connection.is_open
        finally:
            listener.stop()
            _closed(dialer.peer, connection)

    def test_a_clean_close_is_logged_at_info(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        listener, connection, dialer, _ = _listening()
        with caplog.at_level(logging.INFO):
            listener.start()
            assert dialer.peer is not None
            dialer.peer.close()
            assert _until(lambda: not listener.alive)
        try:
            assert any(
                r.levelno == logging.INFO and "closed the connection" in r.getMessage()
                for r in caplog.records
            )
        finally:
            listener.stop()
            connection.close()


class TestAbandonedThread:
    def test_start_replaces_a_thread_stop_could_not_join(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr("punt_lux.domain.hub.listener_thread._JOIN_TIMEOUT", 0.1)
        dialer = _PairDialer()
        connection = DisplayConnection(dialer, 1.0)
        connection.open()
        routed: list[Message] = []
        in_handler = threading.Event()
        release = threading.Event()

        def route(msg: Message) -> None:
            if not in_handler.is_set():
                in_handler.set()
                release.wait(timeout=5)
            routed.append(msg)

        listener = ListenerThread(connection, route, connection.close)
        listener.start()
        assert dialer.peer is not None
        dialer.peer.sendall(encode_message(PongMessage(ts=1.0)))
        assert in_handler.wait(timeout=3)
        listener.stop()
        assert listener.alive  # stuck in its handler, told to stop

        with caplog.at_level(logging.ERROR):
            listener.start()
        release.set()
        dialer.peer.sendall(encode_message(PongMessage(ts=2.0)))
        try:
            assert _until(lambda: PongMessage(ts=2.0) in routed)
            assert "Abandoning" in caplog.text
        finally:
            listener.stop()
            _closed(dialer.peer, connection)

    def test_start_while_running_and_not_stopping_changes_nothing(self) -> None:
        listener, connection, dialer, _ = _listening()
        try:
            listener.start()
            threads = {t for t in threading.enumerate() if t.name == "lux-listener"}
            listener.start()
            assert {
                t for t in threading.enumerate() if t.name == "lux-listener"
            } == threads
        finally:
            listener.stop()
            _closed(dialer.peer, connection)


class TestARaisingRoute:
    def test_a_handler_that_raises_costs_its_message_not_the_listener(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        dialer = _PairDialer()
        connection = DisplayConnection(dialer, 1.0)
        connection.open()
        routed: list[Message] = []

        def route(msg: Message) -> None:
            if msg == PongMessage(ts=1.0):
                raise RuntimeError("the handler blew up")
            routed.append(msg)

        listener = ListenerThread(connection, route, connection.close)
        with caplog.at_level(logging.ERROR):
            listener.start()
            assert dialer.peer is not None
            dialer.peer.sendall(
                encode_message(PongMessage(ts=1.0))
                + encode_message(PongMessage(ts=2.0))
            )
            assert _until(lambda: routed == [PongMessage(ts=2.0)])
        try:
            assert listener.alive
            (record,) = [r for r in caplog.records if r.levelno == logging.ERROR]
            assert "PongMessage" in record.getMessage()
            assert "pair" in record.getMessage()
        finally:
            listener.stop()
            _closed(dialer.peer, connection)

    def test_the_connection_stays_open_after_a_failed_route(self) -> None:
        dialer = _PairDialer()
        connection = DisplayConnection(dialer, 1.0)
        connection.open()

        def route(_msg: Message) -> None:
            raise RuntimeError("always")

        listener = ListenerThread(connection, route, connection.close)
        listener.start()
        try:
            assert dialer.peer is not None
            dialer.peer.sendall(encode_message(PongMessage(ts=1.0)))
            time.sleep(0.3)
            assert connection.is_open
            assert listener.alive
        finally:
            listener.stop()
            _closed(dialer.peer, connection)


class TestTellingTheLink:
    def _listening_with(
        self, told: list[str]
    ) -> tuple[ListenerThread, DisplayConnection, _PairDialer]:
        dialer = _PairDialer()
        connection = DisplayConnection(dialer, 1.0)
        connection.open()

        def broken() -> None:
            told.append("broken")
            connection.close()

        return ListenerThread(connection, lambda _m: None, broken), connection, dialer

    def test_a_display_that_closes_the_stream_is_reported_and_the_link_closes(
        self,
    ) -> None:
        told: list[str] = []
        listener, connection, dialer = self._listening_with(told)
        listener.start()
        assert dialer.peer is not None
        dialer.peer.close()
        try:
            assert _until(lambda: told == ["broken"])
            assert _until(lambda: not connection.is_open)
        finally:
            listener.stop()
            connection.close()

    def test_a_malformed_frame_is_reported_to_the_link(self) -> None:
        told: list[str] = []
        listener, connection, dialer = self._listening_with(told)
        listener.start()
        assert dialer.peer is not None
        bad = b"[1]"
        dialer.peer.sendall(struct.pack(HEADER_FORMAT, len(bad)) + bad)
        try:
            assert _until(lambda: told == ["broken"])
        finally:
            listener.stop()
            _closed(dialer.peer, connection)

    def test_a_read_failure_on_an_open_connection_is_a_warning_and_reported(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        told: list[str] = []
        listener, connection, dialer = self._listening_with(told)

        def fails(_connection: DisplayConnection, _timeout: float) -> bytes | None:
            raise OSError("the socket fell over")

        monkeypatch.setattr(DisplayConnection, "poll_chunk", fails)
        with caplog.at_level(logging.WARNING):
            listener.start()
            assert _until(lambda: told == ["broken"])
        try:
            warned = [r for r in caplog.records if r.levelno == logging.WARNING]
            assert any("pair" in r.getMessage() for r in warned)
        finally:
            listener.stop()
            _closed(dialer.peer, connection)

    def test_a_deliberate_close_is_debug_and_not_reported(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        told: list[str] = []
        listener, connection, dialer = self._listening_with(told)
        with caplog.at_level(logging.DEBUG):
            listener.start()
            connection.close()
            assert _until(lambda: not listener.alive)
        try:
            assert told == []
            assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        finally:
            listener.stop()
            _closed(dialer.peer, connection)

    def test_a_failed_route_logs_a_bounded_repr_of_the_message(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        dialer = _PairDialer()
        connection = DisplayConnection(dialer, 1.0)
        connection.open()

        def route(_msg: Message) -> None:
            raise RuntimeError("no")

        listener = ListenerThread(connection, route, connection.close)
        with caplog.at_level(logging.ERROR):
            listener.start()
            assert dialer.peer is not None
            dialer.peer.sendall(
                encode_message(PongMessage(ts=1.0)),
            )
            assert _until(lambda: bool(caplog.records))
        try:
            assert "ts=1.0" in caplog.text
        finally:
            listener.stop()
            _closed(dialer.peer, connection)
