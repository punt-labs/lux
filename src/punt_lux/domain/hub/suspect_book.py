"""SuspectBook -- the scenes a display may still hold from dials that ended before.

A display keeps a departed dial's scenes installed, so a scene left unacked when the
Hub, or the keepalive, ended a dial can still crash the display on the next one. The
book carries those scenes from dial to dial and decides, as each dial settles, who is
a suspect of the death it leaves, and keeps each death until the replicator takes it:

- a dial the Hub ended charges nothing; what it still owed is carried;
- a dial the display ended charges what it owed together with the carried scenes, and
  the book is then empty;
- a dial the keepalive or the probe gave up on charges the same, and carries it too,
  since the display may outlive the dial.

An ack read on a dial clears what earlier dials carried, because the display acks only
after a swap that completed every scene it already held. The deaths wait in order and
are never dropped, since a dropped death is a scene never charged; past a few dozen the
book says so.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.dial_death import DialDeath

if TYPE_CHECKING:
    from punt_lux.domain.hub.settlement import Settlement
    from punt_lux.domain.ids import SceneId

logger = logging.getLogger(__name__)

__all__ = ["SuspectBook"]

# Deaths a replicator has not yet charged. The queue holds one per dial and is never
# trimmed: a dropped death is a scene never charged. Past this many it says so.
_PENDING_DEATHS_WARNING = 64


@final
class SuspectBook:
    """Carry suspects across dials; turn each settled dial into its death, if any.

    Not thread-safe: the connection settles dials one at a time under its state lock.
    """

    _carried: frozenset[SceneId]
    _deaths: deque[DialDeath]  # not yet charged, oldest first
    __slots__ = ("_carried", "_deaths")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._carried = frozenset()
        self._deaths = deque()
        return self

    @property
    def carried(self) -> frozenset[SceneId]:
        """The scenes earlier dials left behind and no ack has cleared."""
        return self._carried

    def settle(self, settlement: Settlement, endpoint: str) -> None:
        """Account for one dial that has ended; queue the death it leaves, if any.

        No death is queued when the Hub ended the dial (its owed scenes are carried
        instead), or when neither the dial nor the book holds a suspect.
        """
        owed = frozenset(settlement.owed)
        earlier: frozenset[SceneId] = frozenset() if settlement.acked else self._carried
        if settlement.cause == "hub":
            self._carried = earlier | owed
            return
        suspects: frozenset[SceneId] = owed | earlier
        self._carried = suspects if settlement.cause == "unresponsive" else frozenset()
        if suspects:
            self._queue(DialDeath(suspects, endpoint, settlement.cause))

    def take_death(self) -> DialDeath | None:
        """Hand over the oldest death not yet charged; each is handed over once."""
        return self._deaths.popleft() if self._deaths else None

    def _queue(self, death: DialDeath) -> None:
        """Keep a death for the replicator: never dropped, but never unnoticed."""
        self._deaths.append(death)
        if len(self._deaths) > _PENDING_DEATHS_WARNING:
            logger.warning(
                "%d display deaths wait to be charged: is the replicator running?",
                len(self._deaths),
            )
