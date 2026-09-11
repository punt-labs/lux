"""CrossHostListener -- the Display's opt-in second listening socket (DES-090 W8).

A ``ssl.SSLSocket`` is a ``socket.socket`` subtype, so once a handshake
completes the connection joins ``SocketListener``'s ordinary client set and
is indistinguishable from an ``AF_UNIX`` one (system.tex
§"Coexistence with the Local Fast Path"). What this module owns is the span
*before* that: accept must never hand a freshly-connected peer to the
ordinary path until its TLS handshake -- including client-certificate
verification -- has fully completed, and that handshake must never block
the render thread, which already drives every other network wait on this
single frame-by-frame cadence. A peer that completes the TCP handshake and
then stalls or trickles its ``ClientHello`` gets exactly one bounded budget
of wall-clock time, never an unbounded block (T1's opportunistic scanner).
"""

from __future__ import annotations

import contextlib
import logging
import select
import socket
import ssl
import time
from typing import Literal, Self, final

from punt_lux.display.nonblocking import set_nonblocking

logger = logging.getLogger(__name__)

__all__ = ["CrossHostListener"]

# Generous for a legitimate peer's round trip; tight enough that a stalled or
# slow-rolled peer cannot hold a pending-handshake slot indefinitely.
_HANDSHAKE_BUDGET = 5.0

# Mirrors SocketListener's own AF_UNIX backlog -- a briefly-stalled accept
# loop must not misread a queued-but-not-yet-accepted peer as refused.
_LISTEN_BACKLOG = 128

_HandshakeOutcome = Literal["pending", "ready", "failed"]


@final
class _PendingHandshake:
    """One accepted, not-yet-verified TLS socket and its drop deadline."""

    _sock: ssl.SSLSocket
    _deadline: float
    __slots__ = ("_deadline", "_sock")

    def __new__(cls, sock: ssl.SSLSocket, deadline: float) -> Self:
        self = super().__new__(cls)
        self._sock = sock
        self._deadline = deadline
        return self

    @property
    def sock(self) -> ssl.SSLSocket:
        """Return the wrapped, not-yet-verified socket."""
        return self._sock

    def is_expired(self, now: float) -> bool:
        """Return whether ``now`` (monotonic) has passed this entry's deadline."""
        return now >= self._deadline

    def pump(self) -> _HandshakeOutcome:
        """Drive one non-blocking ``do_handshake()`` step.

        ``SSLWantReadError``/``SSLWantWriteError`` are the expected retry
        signals on a non-blocking socket -- report "pending" and the caller
        tries again next frame. Any other ``ssl.SSLError`` (untrusted CA,
        bad cert, protocol failure) or a torn transport is a hard reject,
        closed the same as an expired deadline.
        """
        try:
            self._sock.do_handshake()
        except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
            return "pending"
        except (ssl.SSLError, OSError):
            return "failed"
        return "ready"


@final
class CrossHostListener:
    """The Display's opt-in TLS listening socket: mutual auth, bounded handshake.

    Fail-closed by construction: no listener exists until a caller binds
    one via :meth:`setup`, mirroring ``LoopbackTransportPolicy``'s own "no
    listener exists until asked for" default. Every accepted socket sits in
    a pending-handshake set -- kept separate from ``SocketListener``'s own
    client dicts -- until its handshake completes; only then is it hedged
    over to the caller (:meth:`pump_ready`'s return value) to promote into
    the ordinary reader set. This class never touches that ordinary set
    itself: it has no knowledge of ``_clients``/``_readers``, only of raw
    and pending sockets.
    """

    _server_sock: socket.socket | None
    _ssl_context: ssl.SSLContext
    _pending: dict[int, _PendingHandshake]
    _handshake_budget: float
    __slots__ = ("_handshake_budget", "_pending", "_server_sock", "_ssl_context")

    def __new__(
        cls, ssl_context: ssl.SSLContext, handshake_budget: float = _HANDSHAKE_BUDGET
    ) -> Self:
        self = super().__new__(cls)
        self._server_sock = None
        self._ssl_context = ssl_context
        self._pending = {}
        self._handshake_budget = handshake_budget
        return self

    @property
    def server_sock(self) -> socket.socket | None:
        """Return the listening socket, or ``None`` before :meth:`setup`."""
        return self._server_sock

    @property
    def pending_count(self) -> int:
        """Return the number of sockets awaiting a completed handshake."""
        return len(self._pending)

    def setup(self, host: str, port: int) -> None:
        """Bind and listen on ``host:port``. Fails loud on any bind error.

        Unlike ``SocketListener.setup``'s self-arbitrating ``AF_UNIX`` bind
        (many processes racing one well-known path), a TCP host:port is
        this one Display's own explicit configuration -- there is no
        concurrent-binder race to arbitrate, so a bind failure is always a
        real misconfiguration (port in use, no permission) and propagates.
        """
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            sock.listen(_LISTEN_BACKLOG)
            set_nonblocking(sock)
        except OSError:
            sock.close()  # never leak the bound fd on a failed setup
            raise
        self._server_sock = sock

    def shutdown(self) -> None:
        """Close the listening socket and every pending (unverified) connection."""
        for pending in self._pending.values():
            with contextlib.suppress(OSError):
                pending.sock.close()
        self._pending.clear()
        if self._server_sock is not None:
            with contextlib.suppress(OSError):
                self._server_sock.close()
            self._server_sock = None

    def accept_pending(self) -> None:
        """Accept any newly-connected peers into the pending-handshake set.

        Never blocks: the raw socket is wrapped in the server's
        ``ssl.SSLContext`` non-blocking, with ``do_handshake_on_connect=False``
        so the wrap itself cannot stall -- the handshake is driven
        explicitly, one step per frame, by :meth:`pump_ready`.
        """
        if self._server_sock is None:
            return
        readable, _, _ = select.select([self._server_sock], [], [], 0)
        if not readable:
            return
        try:
            raw, _ = self._server_sock.accept()
        except (BlockingIOError, OSError):
            return
        set_nonblocking(raw)
        tls_sock = self._ssl_context.wrap_socket(
            raw, server_side=True, do_handshake_on_connect=False
        )
        deadline = time.monotonic() + self._handshake_budget
        self._pending[tls_sock.fileno()] = _PendingHandshake(tls_sock, deadline)

    def pump_ready(self) -> list[ssl.SSLSocket]:
        """Drive every pending handshake one step; return newly-verified sockets.

        A pending connection past its deadline is dropped unconditionally,
        mid-handshake if need be -- the fail-closed backstop against a
        stalled or slow-rolled peer. Each remaining pending socket gets
        exactly one non-blocking ``do_handshake()`` call this frame,
        mirroring the render loop's own per-frame cadence; this method
        never waits.
        """
        now = time.monotonic()
        ready: list[ssl.SSLSocket] = []
        for fd in list(self._pending):
            pending = self._pending[fd]
            if pending.is_expired(now):
                logger.warning("cross-host handshake deadline expired for fd=%d", fd)
                self._drop(fd)
                continue
            outcome = pending.pump()
            if outcome == "pending":
                continue
            del self._pending[fd]
            if outcome == "ready":
                ready.append(pending.sock)
            else:
                logger.warning("cross-host handshake failed for fd=%d", fd)
                with contextlib.suppress(OSError):
                    pending.sock.close()
        return ready

    def _drop(self, fd: int) -> None:
        """Remove and close a pending entry by fd; a no-op if already gone."""
        pending = self._pending.pop(fd, None)
        if pending is not None:
            with contextlib.suppress(OSError):
                pending.sock.close()
