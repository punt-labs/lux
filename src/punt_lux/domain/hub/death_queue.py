"""DeathQueue -- the deaths dials left behind that nobody has charged yet.

A death is the record a dial leaves when it ends: the scenes it still owed. It is
queued by the :class:`~punt_lux.domain.hub.suspect_book.SuspectBook` as the dial
settles, and taken by the one charger, which is the only holder of the queue: it is
handed out once, as the write seat is, and a second asker is refused. The deaths wait
in order and are never dropped, since a dropped death is a scene never charged; past a
few dozen the queue says so. A death whose charge failed is put back at the head, so
the next look charges it again before any later one.

A ``deque`` makes each of its operations atomic, so the queue takes no lock of its own
and adds none to the lock order.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_death import DialDeath

logger = logging.getLogger(__name__)

__all__ = ["DeathQueue"]

# Past this many waiting deaths the queue says so: nobody is charging them.
_PENDING_DEATHS_WARNING = 64


@final
class DeathQueue:
    """Deaths not yet charged, oldest first."""

    _deaths: deque[DialDeath]
    __slots__ = ("_deaths",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._deaths = deque()
        return self

    def queue(self, death: DialDeath) -> None:
        """Keep a death for the charger: never dropped, but never unnoticed."""
        self._deaths.append(death)
        if len(self._deaths) > _PENDING_DEATHS_WARNING:
            logger.warning(
                "%d display deaths wait to be charged: is the replicator running?",
                len(self._deaths),
            )

    def take(self) -> DialDeath | None:
        """Hand over the oldest death; each is handed over once."""
        try:
            return self._deaths.popleft()
        except IndexError:
            return None

    def put_back(self, death: DialDeath) -> None:
        """Return a death whose charge failed to the head: it is charged next."""
        self._deaths.appendleft(death)
