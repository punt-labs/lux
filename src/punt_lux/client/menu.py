"""``client.menu.*`` -- the noun-grouped Menu accessor over the commands layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands import menu_ls, menu_set
from punt_lux.commands._ports import Ctx

if TYPE_CHECKING:
    from punt_lux.commands._ports import MenuOps
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import MenuList, Ok, OpError
    from punt_lux.operations.models.menu_results import SetMenuRequest


@final
class MenuAccessor:
    """The ``client.menu.*`` verbs -- ``ls`` and ``set`` this cycle.

    ``client.menu.get(label)`` is tracked as ``lux-m69c``; its command is not
    yet on the ABC path, so the accessor method lands with that follow-on bead.
    """

    _ops: MenuOps
    _identity: ClientIdentity
    __slots__ = ("_identity", "_ops")

    def __new__(cls, ops: MenuOps, identity: ClientIdentity) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._identity = identity
        return self

    def _ctx(self) -> Ctx[MenuOps]:
        return Ctx(ops=self._ops, identity=self._identity)

    async def ls(self) -> MenuList | OpError:
        """Return the Hub-authoritative menu bar."""
        return await menu_ls.execute(self._ctx())

    async def set(self, request: SetMenuRequest | OpError) -> Ok | OpError:
        """Install ``request`` as the new menu bar."""
        return await menu_set.execute(self._ctx(), request)
