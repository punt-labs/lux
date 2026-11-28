"""``service register`` -- register the service the caller serves.

A client that answers typed requests (the terminal helper is the first) registers
the service it serves, keyed by the host its identity declared. Registration needs
a live listen leg and an identity, as a menu callback does, and is withdrawn when
the leg goes.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_error
from punt_lux.commands._result import CommandResult
from punt_lux.wire.operations import Ok, OpError

if TYPE_CHECKING:
    from punt_lux.wire.operations import Scope
    from punt_lux.wire.operations.service_requests import RegisterServiceRequest
    from punt_lux.wire.ops import Ctx, ServiceOps


@final
class ServiceRegisterCommand:
    """Register the caller's service and render the typed outcome."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self,
        ctx: Ctx[ServiceOps],
        request: RegisterServiceRequest | OpError,
        *,
        scope: Scope,
    ) -> Ok | OpError:
        """Register ``request`` for the caller's scope and return the typed outcome."""
        return await asyncio.to_thread(ctx.ops.register_service, request, scope=scope)

    async def __call__(
        self,
        ctx: Ctx[ServiceOps],
        request: RegisterServiceRequest | OpError,
        *,
        scope: Scope,
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        if isinstance(request, OpError):
            return render_error(request)
        result = await self.execute(ctx, request, scope=scope)
        if isinstance(result, OpError):
            return render_error(result)
        return CommandResult(
            text=f"registered:{request.service}",
            json_data={"service": request.service},
        )


service_register: ServiceRegisterCommand = ServiceRegisterCommand()
