"""ListenerThread -- the background reader over the display connection."""

from __future__ import annotations

import socket
import threading
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.handshake_outcome import HandshakeResult
from punt_lux.domain.hub.listener_thread import ListenerThread
from punt_lux.protocol import PingMessage, ReadyMessage, encode_message

if TYPE_CHECKING:
    from collections.abc import Callable

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
    listener = ListenerThread(connection, routed.append)
    return listener, connection, dialer, routed


class TestRouting:
    def test_every_decoded_message_is_routed(self) -> None:
        listener, connection, dialer, routed = _listening()
        listener.start()
        try:
            assert dialer.peer is not None
            dialer.peer.sendall(encode_message(PingMessage(ts=1.0)))
            dialer.peer.sendall(encode_message(PingMessage(ts=2.0)))
            assert _until(lambda: len(routed) == 2)
            assert routed == [PingMessage(ts=1.0), PingMessage(ts=2.0)]
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
            wire = encode_message(PingMessage(ts=3.0))
            dialer.peer.sendall(wire[:3])
            time.sleep(0.2)
            assert routed == []
            dialer.peer.sendall(wire[3:])
            assert _until(lambda: routed == [PingMessage(ts=3.0)])
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

        listener = ListenerThread(connection, route)
        holder.append(listener)
        listener.start()
        try:
            assert dialer.peer is not None
            dialer.peer.sendall(encode_message(PingMessage()))
            assert _until(lambda: bool(seen))
            assert seen == [True]
            assert listener.is_current is False
        finally:
            listener.stop()
            connection.close()
            if dialer.peer is not None:
                dialer.peer.close()
