"""DisplayLiveness — keep luxd's display connection live so clicks keep flowing.

luxd learns a dropped display connection only when it next tries to push a scene.
Between pushes the display has no client to forward interactions to, so every
click in that window is fired display-side and dropped -- a silent gap the
operator experiences as "selection stopped working". This worker closes that gap:
it periodically proves the connection live with a ping and, on failure, drops and
reconnects so luxd re-registers as a display client. The silent window is bounded
to about one keepalive interval instead of the time until the next scene push.

The worker only reuses the connection registry the rest of luxd already shares;
its ``get`` reconnects and re-registers, and its ``drop`` closes a dead socket so
the next ``get`` binds fresh. The registry serializes those against the
replicator and the tool threads, so this worker adds no new lock.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

from punt_lux.connection_timing import CONNECTION_TIMING

if TYPE_CHECKING:
    from punt_lux.protocol import PongMessage

logger = logging.getLogger(__name__)

__all__ = [
    "DisplayLiveness",
    "KeepaliveClients",
    "KeepaliveConnection",
]

# Bound the join at stop so a wedged final ping cannot hang shutdown.
_STOP_JOIN_TIMEOUT = 3.0


@runtime_checkable
class KeepaliveConnection(Protocol):
    """The one capability the keepalive needs of a connection: a ping round-trip."""

    def ping(self, timeout: float | None = ...) -> PongMessage | None:
        """Send a ping and return the pong, or ``None`` if none arrived in time."""
        ...


@runtime_checkable
class KeepaliveClients(Protocol):
    """Hands out the display connection (reconnecting) and drops a dead one."""

    def get(self) -> KeepaliveConnection:
        """Return the connected client, reconnecting and re-registering if dropped."""
        ...

    def drop(self) -> None:
        """Close the current connection so the next ``get`` binds a fresh one."""


@final
class DisplayLiveness:
    """Background worker that keeps luxd's display connection live and registered.

    Starts and stops with luxd. Each cycle proves the connection with a ping; a
    failed ping drops the dead connection and reconnects at once, so luxd is a
    registered display client again within about one interval and interactions
    resume instead of being dropped display-side.
    """

    _clients: KeepaliveClients
    _interval: float
    _ping_timeout: float
    _stop: threading.Event
    _thread: threading.Thread | None
    __slots__ = ("_clients", "_interval", "_ping_timeout", "_stop", "_thread")

    def __new__(
        cls,
        clients: KeepaliveClients,
        interval: float = CONNECTION_TIMING.keepalive_interval,
        ping_timeout: float = CONNECTION_TIMING.ping_timeout,
    ) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._interval = interval
        self._ping_timeout = ping_timeout
        self._stop = threading.Event()
        self._thread = None
        return self

    def start(self) -> None:
        """Start the keepalive thread. Idempotent while already running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="lux-liveness", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Ask the worker to stop and join it, bounded so shutdown cannot hang."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=_STOP_JOIN_TIMEOUT)
            if thread.is_alive():
                logger.warning("liveness worker did not stop within timeout")
            else:
                self._thread = None

    def check_once(self) -> None:
        """Prove the connection; on a twice-failed probe, drop and reconnect.

        The re-probe before dropping spares a connection a concurrent
        ``SendRecovery`` just reconnected, avoiding a needless close. The reconnect
        in the same cycle re-registers luxd at once, so a real drop swallows at
        most about one interval of interactions, not everything until the next push.
        """
        if self._probe() or self._probe():
            return
        logger.warning("display connection unresponsive; dropping and reconnecting")
        self._clients.drop()
        self._probe()

    def _run(self) -> None:
        """Tick every interval until stopped, surviving any cycle failure.

        A raising cycle must never kill the thread: nothing restarts it, so one
        escape would silently retire the keepalive for the life of luxd and reopen
        the dropped-click window. Every exception is logged and the loop continues.
        """
        while not self._stop.wait(self._interval):
            try:
                self.check_once()
            except Exception:
                logger.exception("liveness cycle failed; continuing")

    def _probe(self) -> bool:
        """Return whether a ``get`` + ping round-trip succeeded.

        ``get`` reconnects a dropped connection before the ping, so success also
        means luxd is a registered display client. A connect that cannot complete
        surfaces as ``RuntimeError`` (``ClientRegistry`` wraps a refused socket,
        spawn failure, or handshake timeout) and a dead ping send as ``OSError``;
        both are a failed probe, never an escape that could kill the worker.
        """
        try:
            return self._clients.get().ping(self._ping_timeout) is not None
        except (OSError, RuntimeError) as exc:
            logger.warning("liveness probe failed: %s", exc)
            return False
