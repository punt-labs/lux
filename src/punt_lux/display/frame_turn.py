"""FrameTurn -- one frame's network turn, and what is flushed once its swap completes.

Each frame the display takes its turn with the sockets before it draws: accept new
clients, advance the cross-host TLS leg, poll every client, then draw and flush what
the clients are owed. The turn arms one bounded send deadline for all of it, so a burst
of pongs and query responses under Hub backpressure cannot stack per-send waits and
wedge the render thread past the ping timeout or the macOS "not responding" threshold;
sends past the budget defer, they do not block. After the buffer swap completes the
turn flushes what only a completed swap may release: the paint clock, the acks held for
the scenes the frame installed (under their own one budget, see
:meth:`~punt_lux.display.client_sender.ClientSender.release_acks`), and a screenshot
waiting for the frame just painted.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.client_queries import ClientQueries
    from punt_lux.display.client_sender import ClientSender
    from punt_lux.display.cross_host_pump import CrossHostPump
    from punt_lux.display.paint_clock import PaintClock
    from punt_lux.display.socket_server import SocketListener

logger = logging.getLogger(__name__)

__all__ = ["FrameTurn"]

# Total wall-clock a frame's synchronous sends may wait on a backpressured Hub.
# Below the 1 s ping timeout and ~2 s macOS "not responding" threshold, so a
# slow-but-alive peer never wedges the render thread; over-budget sends defer.
_FRAME_SEND_BUDGET = 0.1


@final
class FrameTurn:
    """Takes the display's turn with its sockets each frame; flushes after a swap."""

    _sockets: SocketListener
    _sender: ClientSender
    _cross_host: CrossHostPump | None  # PY-TS-14 OK: the cross-host leg is opt-in
    _paint_clock: PaintClock
    _queries: ClientQueries
    __slots__ = ("_cross_host", "_paint_clock", "_queries", "_sender", "_sockets")

    def __new__(
        cls,
        *,
        sockets: SocketListener,
        sender: ClientSender,
        cross_host: CrossHostPump | None,
        paint_clock: PaintClock,
        queries: ClientQueries,
    ) -> Self:
        self = super().__new__(cls)
        self._sockets = sockets
        self._sender = sender
        self._cross_host = cross_host
        self._paint_clock = paint_clock
        self._queries = queries
        return self

    def run(self, draw: Callable[[], None]) -> None:
        """Take the sockets' turn, then ``draw``, all under one send deadline."""
        self._sender.set_frame_deadline(time.monotonic() + _FRAME_SEND_BUDGET)
        try:
            self._sockets.accept_connections()
            self.pump_cross_host()
            self._sockets.poll_clients()
            draw()
        finally:
            self._sender.clear_frame_deadline()

    def pump_cross_host(self) -> None:
        """Advance the opt-in cross-host TLS listener one frame (DES-090 W10).

        ``accept_pending()`` is called **at most once per frame** -- the
        listener's pending-handshake self-bounding depends on that cadence --
        and every socket whose mTLS handshake completed this frame is promoted
        onto the ordinary client set, where the content gate holds it to the
        same verify -> identify -> content order the ``AF_UNIX`` leg follows
        (Invariant 1). Fail-closed: no listener configured, nothing happens.

        A transport error accepting or pumping the cross-host leg drops that
        frame's cross-host work and keeps rendering -- a wedged listen socket
        must never stop the display or freeze the same-host ``AF_UNIX`` leg
        (the render loop is a crash boundary). The log fires only on the
        exceptional path, never per frame.
        """
        listener = self._cross_host
        if listener is None:
            return
        try:
            listener.accept_pending()
            ready = listener.pump_ready()
        except OSError as exc:
            logger.warning("cross-host accept/pump failed this frame: %s", exc)
            return
        for tls_sock in ready:
            self._sockets.promote_connection(tls_sock)

    def shutdown(self) -> None:
        """Close the cross-host listen socket and its pending peers, if there is one."""
        if self._cross_host is not None:
            self._cross_host.shutdown()

    def after_swap(self) -> None:
        """Flush what a completed buffer swap releases: GL_FRONT has the frame."""
        self._paint_clock.swapped()
        self._sender.release_acks()
        self._queries.after_swap()
