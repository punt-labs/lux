"""DeathCharger -- charge the display's deaths to the scenes each dial still owed.

The one holder of the connection's death queue. Whoever discovered a death (the
reader, the keepalive, a tool's redial, the replicator's own send) left the same record
on the dial that died; this charges it, once, however and whenever it is looked for. A
dial the Hub ended, or one that owed nothing, left no record, so nothing is charged.
Charging runs before a batch is filtered, so a scene that reaches the threshold is
excluded from the very push that follows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.crash_attribution import CrashAttribution
    from punt_lux.domain.hub.replicator_ports import DeathQueuePort

__all__ = ["DeathCharger"]


@final
class DeathCharger:
    """Takes the pending deaths from its queue and attributes each to its ledger."""

    _deaths: DeathQueuePort
    _attribution: CrashAttribution
    __slots__ = ("_attribution", "_deaths")

    def __new__(cls, deaths: DeathQueuePort, attribution: CrashAttribution) -> Self:
        self = super().__new__(cls)
        self._deaths = deaths
        self._attribution = attribution
        return self

    def charge(self) -> None:
        """Attribute every death not yet charged; each dial is charged once.

        One death at a time. If charging one raises, that death goes back at the head
        of the queue and the error goes on: the next look charges it again before any
        later one, so no death is lost with the failure.
        """
        while (death := self._deaths.take()) is not None:
            try:
                self._attribution.attribute_death(
                    death.suspects, render_error=death.reason
                )
            except Exception:
                self._deaths.put_back(death)
                raise
