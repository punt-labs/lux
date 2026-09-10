"""DisplayLiveness — keep luxd's display connection live so clicks keep flowing.

luxd learns a dropped display connection only when it next tries to push a
scene. Between pushes, every click is fired display-side and dropped -- a
silent gap the operator experiences as "selection stopped working". This
worker closes it: it periodically pings and, on failure, drops and
reconnects, bounding the silent window to about one probe interval.

Reuses the connection registry the rest of luxd already shares; the
registry serializes connect/drop against the replicator and tool threads,
so this worker adds no new lock.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

from punt_lux.connection_timing import CONNECTION_TIMING
from punt_lux.domain.hub.liveness_pacing import LivenessPacing

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
    """Background worker keeping luxd's display connection live and registered.

    Each cycle proves the connection with a ping; a failed ping drops and
    reconnects at once, so interactions resume instead of dropping display-side.
    """

    _clients: KeepaliveClients
    _interval: float
    _ping_timeout: float
    _stop: threading.Event
    _thread: threading.Thread | None
    _pacing: LivenessPacing
    __slots__ = (
        "_clients",
        "_interval",
        "_pacing",
        "_ping_timeout",
        "_stop",
        "_thread",
    )

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
        self._pacing = LivenessPacing()
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

        The re-probe spares a connection a concurrent reconnect just healed.
        ``_pacing`` logs the not-connected transition once, not per cycle.
        """
        if self._probe() or self._probe():
            self._pacing.mark_connected()
            return
        self._pacing.mark_disconnected()
        self._clients.drop()
        self._probe()

    def _run(self) -> None:
        """Tick until stopped; a raising cycle must never kill the thread.

        The interval relaxes while disconnected and snaps back once a probe
        answers, per ``_pacing``.
        """
        interval = self._interval
        while not self._stop.wait(interval):
            try:
                self.check_once()
            except Exception:
                logger.exception("liveness cycle failed; continuing")
            interval = self._pacing.interval(self._interval)

    def _probe(self) -> bool:
        """Return whether a ``get`` + ping round-trip succeeded.

        No per-failure log — ``check_once`` logs the transition once.
        """
        try:
            return self._clients.get().ping(self._ping_timeout) is not None
        except (OSError, RuntimeError):
            return False
