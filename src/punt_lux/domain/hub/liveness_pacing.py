"""LivenessPacing — the two-speed cadence and once-per-transition logging
``DisplayLiveness`` runs its probe loop at (display-presence-demand-driven.md
§6.4).

Probing every ``_interval`` while genuinely disconnected is needless chatter;
relaxing to ``_DISCONNECTED_PROBE_INTERVAL`` is still prompt for a reconnect
while cutting the noise. This class owns exactly the one bit of state that
decision needs and reports transitions so the caller logs once, not per cycle.
"""

from __future__ import annotations

import logging
from typing import Self, final

logger = logging.getLogger(__name__)

__all__ = ["LivenessPacing"]

# The relaxed probe cadence while no display is connected — a few seconds
# slower than the connected ping interval, visibly relaxed yet still well
# inside "prompt" for a reconnect.
_DISCONNECTED_PROBE_INTERVAL = 5.0


@final
class LivenessPacing:
    """Tracks connected/disconnected state for the liveness worker's cadence."""

    _disconnected: bool
    __slots__ = ("_disconnected",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._disconnected = False
        return self

    def mark_connected(self) -> None:
        """Record a successful probe — back to the fast, connected cadence."""
        self._disconnected = False

    def mark_disconnected(self) -> None:
        """Record a failed probe; log once, on the transition, not per cycle."""
        if not self._disconnected:
            logger.info("display not connected; probing until it returns")
        self._disconnected = True

    def interval(self, connected_interval: float) -> float:
        """Return the wait for the next cycle given the current state."""
        return (
            _DISCONNECTED_PROBE_INTERVAL if self._disconnected else connected_interval
        )
