"""``client.event.*`` -- the Event accessor over the commands layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands import event_ls
from punt_lux.commands._ports import Ctx

if TYPE_CHECKING:
    from punt_lux.commands._ports import EventOps
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import OpError, RecentEvents


@final
class EventAccessor:
    """The ``client.event.*`` verbs -- caller-scoped event log."""

    _ops: EventOps
    _identity: ClientIdentity
    __slots__ = ("_identity", "_ops")

    def __new__(cls, ops: EventOps, identity: ClientIdentity) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._identity = identity
        return self

    async def ls(self, count: int = 50) -> RecentEvents | OpError:
        """Return the last ``count`` events for this caller."""
        ctx: Ctx[EventOps] = Ctx(ops=self._ops, identity=self._identity)
        return await event_ls.execute(ctx, count)
