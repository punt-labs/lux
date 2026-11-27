"""``service ls`` -- list which hosts serve which services."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._result import CommandResult

if TYPE_CHECKING:
    from punt_lux.wire.operations import Scope
    from punt_lux.wire.operations.service_results import ServiceList
    from punt_lux.wire.ops import Ctx, ServiceOps


@final
class ServiceLsCommand:
    """List the registrations, so a caller can see which hosts answer."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[ServiceOps], *, scope: Scope) -> ServiceList:
        """Return every registration, ordered by service then host."""
        return await asyncio.to_thread(ctx.ops.list_services, scope=scope)

    async def __call__(self, ctx: Ctx[ServiceOps], *, scope: Scope) -> CommandResult:
        """Run :meth:`execute` and render one line per registration."""
        result = await self.execute(ctx, scope=scope)
        text = (
            "\n".join(f"{entry.service} {entry.host}" for entry in result.services)
            or "no services registered"
        )
        return CommandResult(text=text, json_data=result.model_dump(mode="json"))


service_ls: ServiceLsCommand = ServiceLsCommand()
