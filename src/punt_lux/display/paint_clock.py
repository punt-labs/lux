"""How long a pushed scene takes to reach the glass.

The Hub attests the time it spends installing a scene; this is the other half,
measured inside the display process: from the moment a scene message arrives to
the buffer swap that first put that scene's pixels on screen::

    paint scene=beads-lux 41 ms

Each half is logged by the process that did the work, so a click that felt slow
can be attributed to one side or the other without either process vouching for
the other's clock.

A scene that arrives into a background tab or a minimized frame is never drawn.
It is forgotten after ``_ABANDON_AFTER`` seconds rather than waiting forever for
a paint that is not coming — otherwise a display left running would accumulate
one stamp per scene it never showed.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, ClassVar, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["PaintClock"]

logger = logging.getLogger(__name__)


@final
class PaintClock:
    """Time each pushed scene from its arrival to the swap that first painted it.

    ``clock`` is injected so a test can drive elapsed time directly rather than
    sleeping through a real render pass.
    """

    _ABANDON_AFTER: ClassVar[float] = 5.0

    _clock: Callable[[], float]
    _arrived: dict[str, float]
    _drawn: set[str]
    __slots__ = ("_arrived", "_clock", "_drawn")

    def __new__(cls, clock: Callable[[], float] = time.perf_counter) -> Self:
        self = super().__new__(cls)
        self._clock = clock
        self._arrived = {}
        self._drawn = set()
        return self

    def received(self, scene_id: str) -> None:
        """Stamp a scene's arrival; a re-push starts that scene's clock again."""
        self._arrived[scene_id] = self._clock()

    def painted(self, scene_id: str) -> None:
        """Note that ``scene_id`` was drawn in the pass now in progress.

        Called every frame for every visible scene, so it does nothing for a
        scene that is not waiting on its first paint.
        """
        if scene_id in self._arrived:
            self._drawn.add(scene_id)

    def swapped(self) -> None:
        """Attest every scene the just-swapped pass painted for the first time."""
        now = self._clock()
        for scene_id in self._drawn:
            elapsed = now - self._arrived.pop(scene_id)
            logger.info("paint scene=%s %d ms", scene_id, round(elapsed * 1000))
        self._drawn.clear()
        self._abandon_undrawn(now)

    def _abandon_undrawn(self, now: float) -> None:
        """Forget scenes that arrived but were never drawn, so the stamps stay few."""
        undrawn = [
            scene_id
            for scene_id, arrived in self._arrived.items()
            if now - arrived > self._ABANDON_AFTER
        ]
        for scene_id in undrawn:
            del self._arrived[scene_id]
            logger.debug(
                "paint scene=%s not drawn within %.0f s", scene_id, self._ABANDON_AFTER
            )
