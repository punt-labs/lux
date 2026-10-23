"""DisplayConnection -- the display socket and every write onto it."""

from __future__ import annotations

import socket
from typing import Self, final

import pytest

from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.domain.hub.handshake_outcome import HandshakeResult
from punt_lux.protocol import (
    FrameReader,
    PingMessage,
    ReadyMessage,
    encode_message,
)
from punt_lux.protocol.messages.wire_vocabulary import CLIENT_VOCABULARY


@final
class _Dialer:
    """Dials by handing out one end of a socket pair, counting the dials."""

    dials: int
    peer: socket.socket | None
    ready: ReadyMessage
    fail: bool

    def __new__(cls, *, fail: bool = False) -> Self:
        self = super().__new__(cls)
        self.dials = 0
        self.peer = None
        self.ready = ReadyMessage()
        self.fail = fail
        return self

    def dial(self, connect_timeout: float) -> HandshakeResult:
        self.dials += 1
        if self.fail:
            raise DisplayNotConnectedError("no display")
        ours, self.peer = socket.socketpair()
        return HandshakeResult(sock=ours, endpoint="pair", ready=self.ready)


def _opened() -> tuple[DisplayConnection, _Dialer]:
    dialer = _Dialer()
    connection = DisplayConnection(dialer, 1.0)
    connection.open()
    return connection, dialer


class TestOpen:
    def test_dials_and_holds_the_socket_and_ready_message(self) -> None:
        connection, dialer = _opened()
        try:
            assert connection.is_open
            assert connection.ready is dialer.ready
        finally:
            connection.close()

    def test_opening_twice_dials_once(self) -> None:
        connection, dialer = _opened()
        try:
            connection.open()
            assert dialer.dials == 1
        finally:
            connection.close()

    def test_a_dial_that_fails_leaves_the_connection_closed(self) -> None:
        connection = DisplayConnection(_Dialer(fail=True), 1.0)

        with pytest.raises(DisplayNotConnectedError):
            connection.open()

        assert not connection.is_open
        assert connection.ready is None

    def test_a_new_connection_holds_nothing(self) -> None:
        connection = DisplayConnection(_Dialer(), 1.0)

        assert not connection.is_open
        assert not connection.is_open
        assert connection.ready is None


class TestClose:
    def test_releases_the_socket_and_ready_message_together(self) -> None:
        connection, _ = _opened()

        connection.close()

        assert not connection.is_open
        assert not connection.is_open
        assert connection.ready is None

    def test_closing_a_closed_connection_is_not_an_error(self) -> None:
        DisplayConnection(_Dialer(), 1.0).close()

    def test_can_be_reopened_after_closing(self) -> None:
        connection, dialer = _opened()
        connection.close()

        connection.open()

        try:
            assert dialer.dials == 2
            assert connection.is_open
        finally:
            connection.close()


class TestRequire:
    def test_returns_the_open_socket(self) -> None:
        connection, _ = _opened()
        try:
            assert connection.require() is not None
        finally:
            connection.close()

    def test_raises_when_never_connected(self) -> None:
        with pytest.raises(RuntimeError, match="open\\(\\) the display connection"):
            DisplayConnection(_Dialer(), 1.0).require()


class TestSend:
    def test_writes_the_encoded_frame_to_the_peer(self) -> None:
        connection, dialer = _opened()
        try:
            connection.send(PingMessage(ts=1.5))
            assert dialer.peer is not None
            reader = FrameReader()
            reader.feed(dialer.peer.recv(4096))
            (received,) = reader.drain_typed(CLIENT_VOCABULARY)
            assert received == PingMessage(ts=1.5)
        finally:
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_a_send_with_no_connection_raises(self) -> None:
        with pytest.raises(RuntimeError, match="Not connected"):
            DisplayConnection(_Dialer(), 1.0).send(PingMessage())


class TestPollChunk:
    def test_returns_what_the_peer_sent(self) -> None:
        connection, dialer = _opened()
        try:
            assert dialer.peer is not None
            dialer.peer.sendall(encode_message(PingMessage(ts=2.0)))
            assert connection.poll_chunk(1.0) == encode_message(PingMessage(ts=2.0))
        finally:
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_empty_bytes_mean_the_display_closed_the_connection(self) -> None:
        connection, dialer = _opened()
        try:
            assert dialer.peer is not None
            dialer.peer.close()
            assert connection.poll_chunk(1.0) == b""
        finally:
            connection.close()

    def test_nothing_in_time_is_none_not_a_close(self) -> None:
        connection, dialer = _opened()
        try:
            assert connection.poll_chunk(0.05) is None
        finally:
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_a_closed_connection_cannot_be_polled(self) -> None:
        connection = DisplayConnection(_Dialer(), 1.0)

        with pytest.raises(OSError, match="closed"):
            connection.poll_chunk(0.05)


class TestEndpoint:
    def test_names_the_display_it_is_open_to(self) -> None:
        connection, dialer = _opened()
        try:
            assert connection.endpoint == "pair"
        finally:
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()

    def test_says_so_when_not_open(self) -> None:
        assert DisplayConnection(_Dialer(), 1.0).endpoint == "not connected"
