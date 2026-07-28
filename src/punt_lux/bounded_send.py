"""BoundedSend — ride out backpressure on a non-blocking socket, or give up.

A full kernel send buffer surfaces as ``BlockingIOError`` (``EAGAIN``) on a
non-blocking socket. That is transient backpressure — a peer momentarily not
reading during a busy frame — not a dead peer. Instead of giving up on it, the
send waits for the socket to become writable and resumes from the unsent offset,
so a partial write never corrupts the framed message the way a non-blocking
``sendall`` would.

The wait is bounded by a deadline the *caller* supplies, not a per-send timeout,
so many sends in one render frame share one budget rather than each blocking the
render thread up to a full timeout. If the deadline passes with bytes still
unsent, the send re-raises ``BlockingIOError``; the caller decides what that
means (defer, not drop — a slow peer is alive). A ``BrokenPipeError`` /
``ConnectionResetError`` / other ``OSError`` from the send itself is a genuine
dead peer and propagates immediately, unbounded — there is nothing to wait for.
"""

from __future__ import annotations

import select
import socket
import time
from typing import Self, final

__all__ = ["BoundedSend"]


@final
class BoundedSend:
    """Send every byte of a message before an absolute deadline, or raise.

    Stateless: the deadline is passed per call so a caller can thread one shared
    deadline through a whole frame's worth of sends. ``BlockingIOError`` means the
    peer did not drain before the deadline (alive but slow); a dead-peer
    ``OSError`` is distinct and passes straight through.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def send(self, sock: socket.socket, data: bytes, deadline: float) -> None:
        """Send all of ``data`` on ``sock`` before ``deadline`` (monotonic), or raise.

        Uses ``send`` with an advancing offset rather than ``sendall`` so a
        would-block after a partial write resumes cleanly instead of losing the
        bytes already accepted. Raises ``BlockingIOError`` if the deadline passes
        with the message unfinished; propagates any dead-peer ``OSError``.
        """
        view = memoryview(data)
        offset = 0
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
