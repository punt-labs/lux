"""``client.event.*`` -- the Event accessor over the operation ports."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.wire.operations import OpError, RecentEvents
    from punt_lux.wire.ops import EventOps


@final
class EventAccessor:
    """Read recent events for this client identity."""

    _ops: EventOps
    __slots__ = "_ops"

    def __new__(cls, ops: EventOps) -> Self:
        """Bind event queries to the caller's identity."""
        self = super().__new__(cls)
        self._ops = ops
        return self

    async def ls(self, count: int = 50) -> RecentEvents | OpError:
        """Return the last ``count`` events for this caller."""
        return await asyncio.to_thread(self._ops.list_recent_events, count)
