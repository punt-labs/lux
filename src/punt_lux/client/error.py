"""``client.error.*`` -- the Error accessor over the commands layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands import error_ls
from punt_lux.commands._ports import Ctx

if TYPE_CHECKING:
    from punt_lux.commands._ports import ErrorOps
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import OpError, RecentErrors


@final
class ErrorAccessor:
    """The ``client.error.*`` verbs -- caller-scoped error log."""

    _ops: ErrorOps
    _identity: ClientIdentity
    __slots__ = ("_identity", "_ops")

    def __new__(cls, ops: ErrorOps, identity: ClientIdentity) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._identity = identity
        return self

    async def ls(self, count: int = 20) -> RecentErrors | OpError:
        """Return the last ``count`` errors for this caller."""
        ctx: Ctx[ErrorOps] = Ctx(ops=self._ops, identity=self._identity)
        return await error_ls.execute(ctx, count)
