"""Shared display-connection recovery timing, tied so one cannot outrun the other.

Two mechanisms cooperate to survive a dropped display connection: luxd's
keepalive (``DisplayLiveness``) reconnects, and the display's interaction buffer
(``PendingInteractions``) holds clicks until it does. They live in different
processes but must agree on one invariant: the buffer must hold an interaction at
least as long as the keepalive's worst-case reconnect, or a click is compensated
away just before the reconnect that would have delivered it.

``ConnectionTiming`` is the single home for that timing so the invariant is
structural, not a comment two files apart: the buffer bound is *derived* from the
keepalive cadence, so tuning the cadence grows the bound with it and neither can
be edited without the other following.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

__all__ = ["CONNECTION_TIMING", "ConnectionTiming"]


@final
@dataclass(frozen=True, slots=True)
class ConnectionTiming:
    """The keepalive cadence and the buffer bound derived from it.

    The keepalive pings every ``keepalive_interval`` and waits ``ping_timeout``
    for each pong; the buffer must outlive the worst-case reconnect those imply.
    ``interaction_max_age`` is computed, never set, so the buffer bound can never
    silently fall below the reconnect it must cover.
    """

    keepalive_interval: float = 2.0
    ping_timeout: float = 1.0
    # Extra hold beyond the reconnect worst case, covering the DisplayClient
    # send-lock stack that can serialize a ping behind an in-flight send and push
    # a real reconnect past the nominal worst case.
    hold_margin: float = 2.5

    @property
    def reconnect_worst_case(self) -> float:
        """Longest time from a drop to a re-registered client.

        Up to one interval elapses before the probe that notices the drop, then
        the failed ping and the reconnect ping each cost up to one ping timeout.
        """
        return self.keepalive_interval + 2 * self.ping_timeout

    @property
    def interaction_max_age(self) -> float:
        """How long the display holds a click so a reconnect can still deliver it."""
        return self.reconnect_worst_case + self.hold_margin


# The one shared instance both tiers read: luxd's keepalive for its cadence, the
# display's buffer for its hold bound.
CONNECTION_TIMING = ConnectionTiming()
