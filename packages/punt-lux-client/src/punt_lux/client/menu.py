"""``client.menu.*`` -- the noun-grouped Menu accessor over the operation ports."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.wire.operations import MenuList, Ok, OpError, Scope
    from punt_lux.wire.operations.menu_results import SetMenuRequest
    from punt_lux.wire.ops import MenuOps


@final
class MenuAccessor:
    """Read the Hub menu and publish this session's menu entries."""

    _ops: MenuOps
    _scope: Scope
    __slots__ = ("_ops", "_scope")

    def __new__(cls, ops: MenuOps, scope: Scope) -> Self:
        """Bind menu operations to the caller's identity and scope."""
        self = super().__new__(cls)
        self._ops = ops
        self._scope = scope
        return self

    async def ls(self) -> MenuList | OpError:
        """Return the Hub-authoritative menu bar."""
        return await asyncio.to_thread(self._ops.list_menus)

    async def set(self, request: SetMenuRequest | OpError) -> Ok | OpError:
        """Install ``request`` as the new menu bar."""
        return await asyncio.to_thread(self._ops.set_menu, request, scope=self._scope)
