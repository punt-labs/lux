"""DialOutbound -- every write onto one dial's socket, one at a time.

Each write holds the dial's socket lock across the ``sendall`` and the bookkeeping
that goes with it (the ack a scene is owed, the reply a ping or query is waiting for),
so the reader cannot take a byte of a reply before its entry exists. A write that
raises may have left half a frame on the wire, so it reports to the dial, which ends
it; the dial, not this object, decides who ended it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.protocol import PingMessage, encode_message

if TYPE_CHECKING:
    import socket
    import threading
    from collections.abc import Callable

    from punt_lux.domain.hub.reply_sink import Pending, ReplySink
    from punt_lux.protocol import (
        Message,
        PongMessage,
        QueryRequest,
        QueryResponse,
        SceneMessage,
    )

__all__ = ["DialOutbound"]


@final
class DialOutbound:
    """Write to one socket under its lock, and report a write that failed."""

    _sock: socket.socket
    _lock: threading.Lock
    _sink: ReplySink
    _require_open: Callable[[], None]
    _socket_failed: Callable[[OSError], None]
    _write_broken: Callable[[], None]
    __slots__ = (
        "_lock",
        "_require_open",
        "_sink",
        "_sock",
        "_socket_failed",
        "_write_broken",
    )

    def __new__(
        cls,
        sock: socket.socket,
        lock: threading.Lock,
        sink: ReplySink,
        *,
        require_open: Callable[[], None],
        socket_failed: Callable[[OSError], None],
        write_broken: Callable[[], None],
    ) -> Self:
        self = super().__new__(cls)
        self._sock = sock
        self._lock = lock
        self._sink = sink
        self._require_open = require_open
        self._socket_failed = socket_failed
        self._write_broken = write_broken
        return self

    def send(self, msg: Message) -> None:
        """Write ``msg``, serialized against every other writer."""
        wire = encode_message(msg)
        self._write_locked(lambda: None, lambda _: self._sock.sendall(wire))

    def send_scene(self, msg: SceneMessage) -> None:
        """Write a scene and record the ack it is owed, in wire order.

        The ledger entry is made under the socket lock, after the write returned:
        the reader cannot take a byte before the lock is released, so the ack can
        never be read before its entry exists, and a write that raised owes none.
        """
        wire = encode_message(msg)

        def write_then_owe(_: None) -> None:
            self._sock.sendall(wire)
            self._sink.owe_ack(msg.id)

        self._write_locked(lambda: None, write_then_owe)

    def send_ping(self, ts: float) -> Pending[float, PongMessage]:
        """Register the ping in flight, then write it; one step under the lock."""
        wire = encode_message(PingMessage(ts=ts))

        def write(pending: Pending[float, PongMessage]) -> Pending[float, PongMessage]:
            self._sock.sendall(wire)
            return pending

        return self._write_locked(lambda: self._sink.expect_pong(ts), write)

    def send_query(self, request: QueryRequest) -> Pending[None, QueryResponse]:
        """Register the query in flight, then write it; one step under the lock."""
        wire = encode_message(request)

        def write(
            pending: Pending[None, QueryResponse],
        ) -> Pending[None, QueryResponse]:
            self._sock.sendall(wire)
            return pending

        return self._write_locked(self._sink.expect_query, write)

    def _write_locked[P, R](
        self, prepare: Callable[[], P], write: Callable[[P], R]
    ) -> R:
        """Run one write under the socket lock; a failure inside it ends the dial.

        ``prepare`` is the bookkeeping that precedes the first byte (registering the
        reply owed): if it refuses, nothing was written and nothing is ended.
        Anything raised inside ``write`` -- whatever it is, a ``BaseException``
        included -- may have left a partial frame on the wire, so the dial is ended,
        after the lock is released. A socket failure is the display's doing (it reset
        the connection, closed its end, or stopped reading until the send timed out);
        anything else that stopped a write is the Hub's.
        """
        writing = False
        try:
            with self._lock:
                self._require_open()
                prepared = prepare()
                writing = True
                return write(prepared)
        except OSError as exc:
            if writing:
                self._socket_failed(exc)
            raise
        except BaseException:
            if writing:
                self._write_broken()
            raise
