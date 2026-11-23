"""``client.session.*`` -- the Session accessor over the operation ports."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.wire.operations import ClientList, OpError, Scope
    from punt_lux.wire.operations.identity import Identified
    from punt_lux.wire.ops import SessionOps


@final
class SessionAccessor:
    """List Hub sessions and identify the current session."""

    _ops: SessionOps
    _scope: Scope
    __slots__ = ("_ops", "_scope")

    def __new__(cls, ops: SessionOps, scope: Scope) -> Self:
        """Bind session operations to the caller's identity and scope."""
        self = super().__new__(cls)
        self._ops = ops
        self._scope = scope
        return self

    async def ls(self) -> ClientList | OpError:
        """List every Hub session and its scope."""
        return await asyncio.to_thread(self._ops.list_clients)

    async def identify(self, declaration: dict[str, object]) -> Identified | OpError:
        """Confirm this client's declared identity against ``declaration``."""
        return await asyncio.to_thread(
            self._ops.identify, declaration, scope=self._scope
        )
