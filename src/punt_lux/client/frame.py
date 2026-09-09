"""``client.frame.*`` -- the noun-grouped Frame accessor over the commands layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands import frame_close
from punt_lux.commands._frame_close_request import FrameCloseRequest
from punt_lux.commands._ports import Ctx

if TYPE_CHECKING:
    from punt_lux.client.frame_deps import FrameAccessorDeps
    from punt_lux.commands._ports import FrameOps
    from punt_lux.operations import Ok, OpError, Scope


@final
class FrameAccessor:
    """The ``client.frame.*`` verbs -- ``close`` this cycle."""

    _ctx: Ctx[FrameOps]
    _scope: Scope
    __slots__ = ("_ctx", "_scope")

    def __new__(cls, deps: FrameAccessorDeps) -> Self:
        self = super().__new__(cls)
        self._ctx = Ctx(ops=deps.ops, identity=deps.identity)
        self._scope = deps.scope
        return self

    async def close(self, frame_id: str) -> Ok | OpError:
        """Close the caller's own ``frame_id`` and tear down its scenes on the Hub."""
        request = FrameCloseRequest(self._ctx, frame_id, self._scope)
        return await frame_close.execute(request)
