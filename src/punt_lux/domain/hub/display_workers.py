"""DisplayWorkers — luxd's background workers over the display connection.

luxd runs two background workers against its one display connection: the
``HubReplicator``, the sole writer that pushes scene state, and the
``DisplayLiveness`` keepalive, which keeps the connection registered so display
clicks keep reaching the Hub. Both start with luxd and stop with it, so this
facade owns starting and stopping the pair as one, and hands the replicator to
the frame-expiry sweep that also drives it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.domain.hub.clients import client_registry
from punt_lux.domain.hub.liveness import DisplayLiveness, KeepaliveClients
from punt_lux.domain.hub.replicator_instance import hub_replicator

if TYPE_CHECKING:
    from punt_lux.domain.hub.liveness import DisplayLiveness as _Liveness
    from punt_lux.domain.hub.replicator import HubReplicator

__all__ = ["display_workers"]


@final
class DisplayWorkers:
    """Start and stop luxd's replicator and connection keepalive as one unit."""

    _replicator: HubReplicator
    _liveness: _Liveness
    __slots__ = ("_liveness", "_replicator")

    def __new__(cls, replicator: HubReplicator, liveness: _Liveness) -> Self:
        self = super().__new__(cls)
        self._replicator = replicator
        self._liveness = liveness
        return self

    @property
    def replicator(self) -> HubReplicator:
        """Return the sole display writer, for the frame-expiry sweep that drives it."""
        return self._replicator

    def start(self) -> None:
        """Start the replicator, then the keepalive that guards its connection."""
        self._replicator.start()
        self._liveness.start()

    def stop(self) -> None:
        """Stop the keepalive first, then flush and stop the replicator."""
        self._liveness.stop()
        self._replicator.stop()


# DisplayLink satisfies KeepaliveConnection at runtime (it has ``ping``); the
# cast bridges the registry's concrete return type to the keepalive's port.
display_workers = DisplayWorkers(
    hub_replicator,
    DisplayLiveness(cast("KeepaliveClients", client_registry)),
)
