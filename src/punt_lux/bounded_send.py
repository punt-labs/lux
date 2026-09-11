"""BoundedSend — ride out backpressure on a non-blocking socket, or give up.

A full kernel send buffer surfaces as ``BlockingIOError`` (``EAGAIN``) on a
non-blocking socket -- transient backpressure from a peer momentarily not
reading during a busy frame, not a dead peer. The send waits for the socket
to become writable and resumes from the unsent offset, so a partial write
never corrupts the framed message the way a non-blocking ``sendall`` would.
A non-blocking TLS socket signals the same backpressure as ``SSLWantWriteError``.

The wait is bounded by a deadline the *caller* supplies, not a per-send timeout,
so many sends in one render frame share one budget rather than each blocking the
render thread up to a full timeout. What the deadline means depends on whether
the frame was already touched:

- **nothing written yet** (a clean would-block): re-raise ``BlockingIOError``.
  The frame never reached the wire, so the caller may keep the connection and
  defer — a slow peer is alive, and re-sending the whole frame later is safe.
- **partially written**: raise ``TornStreamError``. Half a frame is on the wire
  and can never be finished; reusing the connection would write the next frame
  after the torn one, interleaving two frames into protocol corruption. The
  caller must sever, exactly as for a dead peer.

A ``BrokenPipeError`` / ``ConnectionResetError`` / other ``OSError`` from the send
itself is a genuine dead peer and propagates immediately, unbounded.
"""

from __future__ import annotations

import select
import socket
import ssl
import time
from typing import Self, final

__all__ = ["BoundedSend", "TornStreamError"]


class TornStreamError(OSError):
    """A send left a partial frame it cannot finish; the stream must be severed.

    Subclasses ``OSError`` so a caller that already removes a client on a
    dead-peer ``OSError`` severs a torn stream by the same path, never reusing a
    connection that carries half a frame.
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

        Uses ``send`` with an advancing offset rather than ``sendall`` so a
        would-block resumes cleanly. On the deadline, an untouched frame
        re-raises ``BlockingIOError`` to defer; a partial one raises
        ``TornStreamError`` (unusable stream). A zero-byte ``send`` or a
        dead peer's ``OSError`` also propagates -- looping on zero would spin.
        """
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            try:
                sent = sock.send(view[offset:])
            except (BlockingIOError, ssl.SSLWantWriteError, ssl.SSLWantReadError):
                if self._wait_writable(sock, deadline):
                    continue
                if offset > 0:
                    msg = "send deadline hit after a partial write; stream torn"
                    raise TornStreamError(msg) from None
                raise
            if sent == 0:
                msg = "socket accepted zero bytes; stream is dead"
                raise OSError(msg)
            offset += sent

    @staticmethod
    def _wait_writable(sock: socket.socket, deadline: float) -> bool:
        """Return whether ``sock`` became writable before ``deadline`` passed."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        _, writable, _ = select.select([], [sock], [], remaining)
        return bool(writable)
