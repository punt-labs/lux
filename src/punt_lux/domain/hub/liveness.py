"""DisplayLiveness — keep luxd's display connection live so clicks keep flowing.

luxd learns a dropped display connection only when it next tries to push a
scene. Between pushes, every click is fired display-side and dropped -- a
silent gap the operator experiences as "selection stopped working". This
worker closes it: it periodically pings and, on failure, drops and
reconnects, bounding the silent window to about one probe interval.

Reuses the connection registry the rest of luxd already shares -- it
serializes connect/drop against the replicator and tool threads, so this
worker adds no new lock.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.connection_timing import CONNECTION_TIMING
from punt_lux.domain.hub.liveness_pacing import LivenessPacing
from punt_lux.domain.hub.liveness_probe import LivenessProbe

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_ref import DialRef
    from punt_lux.domain.hub.keepalive_ports import KeepaliveClients

logger = logging.getLogger(__name__)

__all__ = ["DisplayLiveness"]

# Bound the join at stop so a wedged final ping cannot hang shutdown.
_STOP_JOIN_TIMEOUT = 3.0


@final
class DisplayLiveness:
    """Background worker keeping luxd's display connection live and registered.

    Each cycle proves the connection with a ping; a failed ping drops and
    reconnects at once, so interactions resume instead of dropping display-side.
    """

    _clients: KeepaliveClients
    _interval: float
    _probe: LivenessProbe
    _stop: threading.Event
    _thread: threading.Thread | None
    _pacing: LivenessPacing
    __slots__ = (
        "_clients",
        "_interval",
        "_pacing",
        "_probe",
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
        self._probe = LivenessProbe(clients, ping_timeout)
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
        """
        probe = self._probe.run()
        if not probe.alive:
            probe = self._probe.run()
        if probe.alive:
            self._pacing.mark_connected()
            return
        self._pacing.mark_disconnected()
        self._reconnect(probe.dial)

    def _reconnect(self, dial: DialRef | None) -> None:
        """Drop the dead dial and re-probe -- a live probe marks connected at
        once, sparing a further disconnected-interval cycle."""
        if dial is not None:  # None: the probe never got a dial, nothing to drop
            self._clients.drop_unresponsive(dial)
        if self._probe.run().alive:
            self._pacing.mark_connected()

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
