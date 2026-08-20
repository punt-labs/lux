"""``client.session.*`` -- the noun-grouped Session accessor over the commands layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands import session_identify, session_ls
from punt_lux.commands._ports import Ctx

if TYPE_CHECKING:
    from punt_lux.commands._ports import SessionOps
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import ClientList, OpError, Scope
    from punt_lux.operations.models.identity import Identified


@final
class SessionAccessor:
    """The ``client.session.*`` verbs -- ``ls`` and ``identify`` this cycle.

    ``client.session.inspect(id)`` is tracked as ``lux-aom6``; its command is
    not yet on the ABC path, so the accessor method lands with that follow-on
    bead.
    """

    _ops: SessionOps
    _identity: ClientIdentity
    _scope: Scope
    __slots__ = ("_identity", "_ops", "_scope")

    def __new__(cls, ops: SessionOps, identity: ClientIdentity, scope: Scope) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._identity = identity
        self._scope = scope
        return self

    def _ctx(self) -> Ctx[SessionOps]:
        return Ctx(ops=self._ops, identity=self._identity)

    async def ls(self) -> ClientList | OpError:
        """List every Hub session and its scope."""
        return await session_ls.execute(self._ctx())

    async def identify(self, declaration: dict[str, object]) -> Identified | OpError:
        """Confirm this client's declared identity against ``declaration``."""
        return await session_identify.execute(
            self._ctx(), declaration, scope=self._scope
        )
