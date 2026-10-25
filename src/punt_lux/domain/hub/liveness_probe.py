"""LivenessProbe -- one ping of the display, and what it proved.

A probe is a ``get`` and a liveness ask. It never raises for a display that is
down or slow: that is its answer. What counts as alive (a ping already in flight is
itself proof) is the connection's rule, asked of it, not restated here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_ref import DialRef
    from punt_lux.domain.hub.keepalive_ports import KeepaliveClients

logger = logging.getLogger(__name__)

__all__ = ["LivenessProbe", "Probe"]


@dataclass(frozen=True, slots=True)
class Probe:
    """One probe's outcome: whether the display answered, and the dial it was on."""

    alive: bool
    dial: DialRef | None  # None: no dial was had, so none can be dropped


@final
class LivenessProbe:
    """Pings the display through the client registry's current connection."""

    _clients: KeepaliveClients
    _timeout: float
    __slots__ = ("_clients", "_timeout")

    def __new__(cls, clients: KeepaliveClients, timeout: float) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._timeout = timeout
        return self

    def run(self) -> Probe:
        """Ask once; the caller logs the not-connected transition, not each probe."""
        try:
            port = self._clients.get().desk.asks()
        except (OSError, DisplayNotConnectedError) as exc:
            logger.debug("liveness probe failed: %s", exc)
            return Probe(alive=False, dial=None)
        try:
            alive = port.probe_alive(self._timeout)
        except (OSError, DisplayNotConnectedError) as exc:
            logger.debug("liveness probe failed: %s", exc)
            alive = False
        return Probe(alive=alive, dial=port.dial)
