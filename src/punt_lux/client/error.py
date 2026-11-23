"""``client.error.*`` -- the Error accessor over the operation ports."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.wire.operations import OpError, RecentErrors
    from punt_lux.wire.ops import ErrorOps


@final
class ErrorAccessor:
    """Read recent errors for this client identity."""

    _ops: ErrorOps
    __slots__ = "_ops"

    def __new__(cls, ops: ErrorOps) -> Self:
        """Bind error queries to the caller's identity."""
        self = super().__new__(cls)
        self._ops = ops
        return self

    async def ls(self, count: int = 20) -> RecentErrors | OpError:
        """Return the last ``count`` errors for this caller."""
        return await asyncio.to_thread(self._ops.list_errors, count)
