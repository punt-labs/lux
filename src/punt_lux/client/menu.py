"""``client.menu.*`` -- the noun-grouped Menu accessor over the commands layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands import menu_ls, menu_set
from punt_lux.commands._ports import Ctx

if TYPE_CHECKING:
    from punt_lux.commands._ports import MenuOps
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import MenuList, Ok, OpError, Scope
    from punt_lux.operations.models.menu_results import SetMenuRequest


@final
class MenuAccessor:
    """Read the Hub menu and publish this session's menu entries."""

    _ops: MenuOps
    _identity: ClientIdentity
    _scope: Scope
    __slots__ = ("_identity", "_ops", "_scope")

    def __new__(cls, ops: MenuOps, identity: ClientIdentity, scope: Scope) -> Self:
        """Bind menu operations to the caller's identity and scope."""
        self = super().__new__(cls)
        self._ops = ops
        self._identity = identity
        self._scope = scope
        return self

    def _ctx(self) -> Ctx[MenuOps]:
        return Ctx(ops=self._ops, identity=self._identity)

    async def ls(self) -> MenuList | OpError:
        """Return the Hub-authoritative menu bar."""
        return await menu_ls.execute(self._ctx())

    async def set(self, request: SetMenuRequest | OpError) -> Ok | OpError:
        """Install ``request`` as the new menu bar."""
        return await menu_set.execute(self._ctx(), request, scope=self._scope)
