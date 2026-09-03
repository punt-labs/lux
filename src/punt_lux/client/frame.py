"""``client.frame.*`` -- the noun-grouped Frame accessor over the commands layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands import frame_close
from punt_lux.commands._ports import Ctx

if TYPE_CHECKING:
    from punt_lux.commands._ports import FrameOps
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import Ok, OpError


@final
class FrameAccessor:
    """The ``client.frame.*`` verbs -- ``close`` this cycle."""

    _ops: FrameOps
    _identity: ClientIdentity
    __slots__ = ("_identity", "_ops")

    def __new__(cls, ops: FrameOps, identity: ClientIdentity) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._identity = identity
        return self

    def _ctx(self) -> Ctx[FrameOps]:
        return Ctx(ops=self._ops, identity=self._identity)

    async def close(self, frame_id: str) -> Ok | OpError:
        """Close ``frame_id`` and tear down its scenes on the Hub."""
        return await frame_close.execute(self._ctx(), frame_id)
