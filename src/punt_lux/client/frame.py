"""``client.frame.*`` -- the noun-grouped Frame accessor over the commands layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands import frame_close, frame_raise
from punt_lux.commands._ports import Ctx
from punt_lux.operations import FrameRef

if TYPE_CHECKING:
    from punt_lux.commands._ports import FrameOps
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import FrameRaise, Ok, OpError


@final
class FrameAccessor:
    """The ``client.frame.*`` verbs -- ``raise_`` and ``close`` this cycle."""

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

    async def raise_(self, frame_id: str) -> FrameRaise | OpError:
        """Raise ``frame_id`` -- resolved within this client's own connection."""
        ref = FrameRef.for_identity(frame_id, self._identity)
        return await frame_raise.execute(self._ctx(), ref)

    async def close(self, frame_id: str) -> Ok | OpError:
        """Close ``frame_id`` and tear down its scenes on the Hub."""
        return await frame_close.execute(self._ctx(), frame_id)
