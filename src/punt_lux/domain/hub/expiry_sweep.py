"""ExpirySweep — the Hub event-loop task that retires frames whose TTL passed.

Frame TTL enforcement needs a clock tick, and the Hub already runs one event
loop (luxd's) with the store mutators and the replicator's dirty queue. This task
lives on that loop: it sleeps until the soonest deadline, sweeps the frames now
due, and marks their scenes dirty so the replicator blanks both tiers — the exact
path a manual frame close takes. It is not a second timer thread; it is one more
store mutator on the loop, serialized with every other write by the store lock.

Sweeping through ``FrameLifecycle.expire_due`` keeps the expiry decision atomic
against a concurrent re-show (see ``FrameLifecycle``), so a frame re-armed with a
fresh TTL is never retired by a stale deadline. When no frame is armed the task
idles at a coarse poll rather than spinning; when one is, it waits exactly until
that deadline.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.ids import SceneId
    from punt_lux.operations.ports import DirtyMarker

__all__ = ["ExpiryFrames", "ExpirySweep"]

# No frame is armed: re-check at this coarse cadence rather than block forever, so
# a deadline armed while idle is picked up within one poll. TTLs are second-scale,
# so a one-second idle poll adds no meaningful slop.
_IDLE_POLL_SECONDS = 1.0


@runtime_checkable
class ExpiryFrames(Protocol):
    """The two frame questions the sweep asks — satisfied by ``FrameLifecycle``."""

    def seconds_until_next(self) -> float | None:
        """Return the wait until the soonest deadline, or None when none are armed."""
        ...

    def expire_due(self) -> frozenset[SceneId]:
        """Remove every frame whose deadline has passed; return the scenes to blank."""
        ...


@final
class ExpirySweep:
    """Drive frame-TTL expiry on the Hub event loop: wait, sweep, repeat."""

    _frames: ExpiryFrames
    _marker: DirtyMarker
    __slots__ = ("_frames", "_marker")

    def __new__(cls, frames: ExpiryFrames, marker: DirtyMarker) -> Self:
        self = super().__new__(cls)
        self._frames = frames
        self._marker = marker
        return self

    def next_wait(self) -> float:
        """Return how long to sleep before the next sweep, in seconds.

        The soonest armed deadline, clamped so a passed deadline sweeps at once; the
        coarse idle poll when nothing is armed.
        """
        wait = self._frames.seconds_until_next()
        return _IDLE_POLL_SECONDS if wait is None else max(wait, 0.0)

    def sweep(self) -> None:
        """Retire every due frame and mark its scenes dirty for the replicator."""
        for scene_id in self._frames.expire_due():
            self._marker.mark_dirty(scene_id)

    async def run(self) -> None:
        """Wait-sweep-repeat until the task is cancelled at shutdown."""
        while True:
            await asyncio.sleep(self.next_wait())
            self.sweep()
