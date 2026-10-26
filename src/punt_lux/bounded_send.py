"""BoundedSend — ride out backpressure on a non-blocking socket, or give up.

A full kernel send buffer surfaces as ``BlockingIOError`` on a non-blocking
socket -- transient backpressure, not a dead peer. The send waits for the
right direction (write, or read for a TLS want-read) and resumes from the
unsent offset, so a partial write never corrupts the frame the way a
non-blocking ``sendall`` would.

The wait is bounded by a deadline the *caller* supplies, not a per-send
timeout, so many sends in one render frame share one budget. On the
deadline: an untouched frame re-raises ``BlockingIOError`` to defer (the
peer is alive; re-sending the whole frame later is safe); a partially
written frame raises ``TornStreamError`` -- reusing the connection would
interleave the next frame after the torn one, so the caller must sever.

A ``BrokenPipeError`` / ``ConnectionResetError`` / other ``OSError`` from the
send itself is a genuine dead peer and propagates immediately, unbounded.
"""

from __future__ import annotations

import select
import socket
import ssl
import time
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

__all__ = ["BoundedSend", "ProgressClock", "TornStreamError"]

_RETRY_ERRORS = (BlockingIOError, ssl.SSLWantWriteError, ssl.SSLWantReadError)


class TornStreamError(OSError):
    """A send left a partial frame it cannot finish; the stream must be severed.

    Subclasses ``OSError`` so a dead-peer-removing caller severs a torn
    stream the same way, never reusing a half-written connection.
    """


@final
class ProgressClock:
    """When a byte last moved on a socket, so a deadline can be re-armed by it.

    A peer that is slow but alive keeps moving bytes; one that has stopped moves none.
    A bound on *elapsed* time cuts the first short, so the bound is on time *without
    progress* instead: every byte that moves restarts the window.
    """

    _last: float
    __slots__ = ("_last",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._last = time.monotonic()
        return self

    def moved(self) -> None:
        """Note that a byte moved just now."""
        self._last = time.monotonic()

    def expires_at(self, window: float) -> float:
        """The monotonic time ``window`` seconds after the last progress."""
        return self._last + window

    def progressed_within(self, window: float) -> bool:
        """Whether a byte moved less than ``window`` seconds ago."""
        return time.monotonic() < self._last + window

    def acquire(self, lock: threading.Lock, window: float) -> bool:
        """Take ``lock``; ``False`` if no byte moves for ``window`` while it is held.

        The wait is re-armed by progress: a lock held by a writer that keeps moving
        bytes is waited for, since that peer is alive, and only silence ends the wait.
        """
        while True:
            if lock.acquire(
                timeout=max(self.expires_at(window) - time.monotonic(), 0.0)
            ):
                return True
            if not self.progressed_within(window):
                return False


@final
class BoundedSend:
    """Send every byte of a message before an absolute deadline, or raise.

    Stateless: the deadline is passed per call so a caller can thread one shared
    deadline through a whole frame's worth of sends. On the deadline a clean
    would-block raises ``BlockingIOError`` (defer) and a partial write raises
    ``TornStreamError`` (sever); a dead-peer ``OSError`` passes straight through.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def send(self, sock: socket.socket, data: bytes, deadline: float) -> None:
        """Send all of ``data`` on ``sock`` before ``deadline`` (monotonic), or raise.

        Advancing offset, not ``sendall``, so a would-block resumes cleanly.
        Waits on the direction the caught exception actually needs --
        ``SSLWantReadError`` means a normal post-handshake TLS event wants a
        read before it can finish writing; selecting only on writability
        would busy-spin the caller for the whole deadline. On the deadline,
        an untouched frame raises ``BlockingIOError`` to defer; a partial one
        raises ``TornStreamError``. A zero-byte ``send`` also propagates.
        """
        self._push(sock, data, lambda: deadline, lambda: None)

    def send_while_progressing(
        self, sock: socket.socket, data: bytes, clock: ProgressClock, window: float
    ) -> None:
        """Send all of ``data`` on ``sock``, unless no byte moves for ``window``.

        The deadline is not a time but a silence: it is ``window`` after the last byte
        that moved on the socket (``clock``), and every byte this send moves restarts
        it. A peer that drains slowly but steadily is never cut short; one that has
        stopped ends the send ``window`` after its last byte, as ``send`` does at its
        deadline.
        """
        self._push(sock, data, lambda: clock.expires_at(window), clock.moved)

    def _push(
        self,
        sock: socket.socket,
        data: bytes,
        due: Callable[[], float],
        moved: Callable[[], None],
    ) -> None:
        """Send ``data``; ``due`` is the deadline now, ``moved`` notes a byte going."""
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            try:
                sent = sock.send(view[offset:])
            except _RETRY_ERRORS as exc:
                wants_read = isinstance(exc, ssl.SSLWantReadError)
                if self._wait_ready(sock, due(), for_read=wants_read):
                    continue
                if offset > 0:
                    msg = "send deadline hit after a partial write; stream torn"
                    raise TornStreamError(msg) from None
                msg = "the send deadline passed before the first byte went out"
                raise BlockingIOError(msg) from None
            if sent == 0:
                msg = "socket accepted zero bytes; stream is dead"
                raise OSError(msg)
            offset += sent
            moved()

    @staticmethod
    def _wait_ready(sock: socket.socket, deadline: float, *, for_read: bool) -> bool:
        """Wait before ``deadline`` for the direction the send needs; whether it came.

        Only that direction is watched: data the peer has sent and nobody has read (a
        TLS socket's post-handshake records) keeps the descriptor readable, and a wait
        for writability that woke on it would call the deadline early.
        """
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        watched = [sock]
        readable, writable, _ = select.select(
            watched if for_read else [], [] if for_read else watched, [], remaining
        )
        return bool(readable if for_read else writable)
