"""BoundedSend — ride out backpressure on a non-blocking socket, or give up.

A full kernel send buffer surfaces as ``BlockingIOError`` (``EAGAIN``) on a
non-blocking socket. That is transient backpressure — a peer momentarily not
reading during a busy frame — not a dead peer, and dropping the connection on it
is the defect this class exists to prevent. Instead it waits for the socket to
become writable and resumes from the unsent offset, so a partial write never
corrupts the framed message the way a non-blocking ``sendall`` would.

The wait is bounded. If the deadline passes with bytes still unsent, the send
re-raises ``BlockingIOError`` so the caller can remove a peer too slow to keep. A
``BrokenPipeError`` / ``ConnectionResetError`` / other ``OSError`` from the send
itself is a genuine dead peer and propagates immediately, unbounded — there is
nothing to wait for.
"""

from __future__ import annotations

import select
import socket
import time
from typing import Self, final

__all__ = ["DEFAULT_BACKPRESSURE_TIMEOUT", "BoundedSend"]

# A full send buffer during a busy frame drains in tens of milliseconds once the
# peer reads again; this ceiling declares a peer that still has not drained "too
# slow to keep" and bounds any render-loop stall the wait imposes.
DEFAULT_BACKPRESSURE_TIMEOUT = 1.0


@final
class BoundedSend:
    """Send every byte of a message within a time bound, or raise.

    ``BlockingIOError`` from the caller's perspective is unambiguous: the peer did
    not drain within the bound. A dead-peer ``OSError`` is distinct and passes
    straight through. The caller keys on that distinction to decide whether to
    retry a client or remove it.
    """

    _timeout: float
    __slots__ = ("_timeout",)

    def __new__(cls, timeout: float = DEFAULT_BACKPRESSURE_TIMEOUT) -> Self:
        self = super().__new__(cls)
        self._timeout = timeout
        return self

    def send(self, sock: socket.socket, data: bytes) -> None:
        """Send all of ``data`` on ``sock``, waiting out backpressure to the bound.

        Uses ``send`` with an advancing offset rather than ``sendall`` so a
        would-block after a partial write resumes cleanly instead of losing the
        bytes already accepted. Raises ``BlockingIOError`` if the bound elapses
        with the message unfinished; propagates any dead-peer ``OSError``.
        """
        view = memoryview(data)
        offset = 0
        deadline = time.monotonic() + self._timeout
        while offset < len(view):
            try:
                offset += sock.send(view[offset:])
            except BlockingIOError:
                if not self._wait_writable(sock, deadline):
                    raise

    @staticmethod
    def _wait_writable(sock: socket.socket, deadline: float) -> bool:
        """Return whether ``sock`` became writable before ``deadline`` passed."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        _, writable, _ = select.select([], [sock], [], remaining)
        return bool(writable)
