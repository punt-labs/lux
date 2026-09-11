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
from typing import Self, final

__all__ = ["BoundedSend", "TornStreamError"]

_RETRY_ERRORS = (BlockingIOError, ssl.SSLWantWriteError, ssl.SSLWantReadError)


class TornStreamError(OSError):
    """A send left a partial frame it cannot finish; the stream must be severed.

    Subclasses ``OSError`` so a dead-peer-removing caller severs a torn
    stream the same way, never reusing a half-written connection.
    """


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
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            try:
                sent = sock.send(view[offset:])
            except _RETRY_ERRORS as exc:
                readable, writable = self._wait_ready(sock, deadline)
                ready = readable if isinstance(exc, ssl.SSLWantReadError) else writable
                if ready:
                    continue
                if offset > 0:
                    msg = "send deadline hit after a partial write; stream torn"
                    raise TornStreamError(msg) from None
                raise BlockingIOError from None
            if sent == 0:
                msg = "socket accepted zero bytes; stream is dead"
                raise OSError(msg)
            offset += sent

    @staticmethod
    def _wait_ready(sock: socket.socket, deadline: float) -> tuple[bool, bool]:
        """Return ``(readable, writable)`` before ``deadline``, in one ``select``
        call -- the caller checks only the direction its exception needs.
        """
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, False
        readable, writable, _ = select.select([sock], [sock], [], remaining)
        return bool(readable), bool(writable)
