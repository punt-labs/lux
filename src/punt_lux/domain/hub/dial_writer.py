"""DialWriter -- one write to a dial's socket, under its line, or the dial is failed.

A write is bookkeeping around a bounded send: what must be registered before the first
byte, the send itself, and what follows the last byte under the same lock hold. A write
that raises from the first byte on may have left half a frame on the wire, so the dial
is told, after the lock is released; the dial, not this object, decides who ended it and
whether the failure is the display's.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    import socket
    from collections.abc import Callable

    from punt_lux.domain.hub.socket_line import SocketLine

__all__ = ["DialWriter"]


@final
class DialWriter:
    """Writes to one dial's socket, one at a time."""

    _sock: socket.socket
    _line: SocketLine
    _require_open: Callable[[], None]
    _failed: Callable[[BaseException], None]
    __slots__ = ("_failed", "_line", "_require_open", "_sock")

    def __new__(
        cls,
        sock: socket.socket,
        line: SocketLine,
        *,
        require_open: Callable[[], None],
        failed: Callable[[BaseException], None],
    ) -> Self:
        self = super().__new__(cls)
        self._sock = sock
        self._line = line
        self._require_open = require_open
        self._failed = failed
        return self

    def write[P, R](
        self, wire: bytes, prepare: Callable[[], P], finish: Callable[[P], R]
    ) -> R:
        """Write ``wire`` under the socket lock, unless no byte moves for ``D``.

        ``prepare`` is the bookkeeping that precedes the first byte (registering the
        reply owed): if it refuses, nothing was written and nothing is ended. ``finish``
        is what follows the last byte, under the same lock hold: the ack entry, or the
        ticket handed back. Anything raised from the first byte on, a ``BaseException``
        included, may have left a partial frame on the wire, so the dial is told.

        The same user-space bounded send on either transport, because ``SO_SNDTIMEO``
        does not bound a TLS write: the socket is made non-blocking for the write alone.
        The bound is ``D`` of *no progress*, not ``D`` of elapsed time: every byte that
        moves on the socket, the write's own included, restarts it, for the wait for
        the lock as for the write. A write that keeps moving bytes is never cut short;
        one that has moved none for ``D``, or a lock still held with no byte moving for
        ``D``, ends the dial as unresponsive. The socket lock is held, so nothing reads
        meanwhile.
        """
        self._line.forbid_store()
        if not self._line.acquire_unless_silent():
            stalled = BlockingIOError("the dial's socket lock was not free in time")
            self._failed(stalled)
            raise stalled
        writing = False
        try:
            try:
                self._require_open()
                prepared = prepare()
                writing = True
                self._sock.settimeout(0.0)
                try:
                    self._line.send(self._sock, wire)
                finally:
                    with contextlib.suppress(OSError):  # closed by its own capture
                        self._sock.settimeout(None)
                return finish(prepared)
            finally:
                self._line.release()
        except BaseException as exc:
            if writing:
                self._failed(exc)
            raise
