"""``client.frame.*`` -- the noun-grouped Frame accessor over the operation ports."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.wire.ops import Ctx

if TYPE_CHECKING:
    from punt_lux.client.frame_deps import FrameAccessorDeps
    from punt_lux.wire.operations import Ok, OpError, Scope
    from punt_lux.wire.ops import FrameOps


@final
class FrameAccessor:
    """Manage this client's display frames."""

    _ctx: Ctx[FrameOps]
    _scope: Scope
    __slots__ = ("_ctx", "_scope")

    def __new__(cls, deps: FrameAccessorDeps) -> Self:
        """Bind the frame accessor to its client dependencies."""
        self = super().__new__(cls)
        self._ctx = Ctx(ops=deps.ops, identity=deps.identity)
        self._scope = deps.scope
        return self

    async def remove(self, frame_id: str) -> Ok | OpError:
        """Remove the caller's own ``frame_id``: tear down its scenes on the Hub."""
        return await asyncio.to_thread(
            self._ctx.ops.remove_frame, frame_id, scope=self._scope
        )
