"""MCP tools for the service registry: register a service, list who serves."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from punt_lux.commands import Ctx as CommandCtx
from punt_lux.commands.service_ls import service_ls as service_ls_command
from punt_lux.commands.service_register import (
    service_register as service_register_command,
)
from punt_lux.tools import tools as _core
from punt_lux.tools._signal import signal
from punt_lux.tools.server import mcp
from punt_lux.tools.tools import scope
from punt_lux.wire.operations.service_requests import RegisterServiceRequest

if TYPE_CHECKING:
    from punt_lux.wire.ops import ServiceOps

__all__ = ["service_ls", "service_register"]


class ServiceTools:
    """The two service tools, each a parse-call-format adapter over the facade."""

    @staticmethod
    def _ctx() -> CommandCtx[ServiceOps]:
        return CommandCtx(ops=_core.OPERATIONS, identity=_core._identity())

    @staticmethod
    def register(service: str) -> str:
        """Register the service the calling session serves, keyed by its host.

        Use this from a client that answers typed requests. The caller must have
        identified itself and hold a listen connection, because requests for the
        service are delivered over that connection; the registration ends with it.

        Returns:
            ``"registered:<service>"`` when the registration is active.

        Raises:
            ToolError: If the name is invalid, the caller has not identified
                itself, has no listen connection, or another connection already
                serves the same service on this host.
        """
        request = RegisterServiceRequest.parse(service)
        result = asyncio.run(
            service_register_command(ServiceTools._ctx(), request, scope=scope())
        )
        return signal(result)

    @staticmethod
    def ls() -> str:
        """List which hosts serve which services.

        Returns:
            One ``<service> <host>`` line per registration, ordered by service then
            host, or ``"no services registered"``.
        """
        result = asyncio.run(service_ls_command(ServiceTools._ctx(), scope=scope()))
        return signal(result)


service_register = mcp.tool(name="service_register")(ServiceTools.register)
service_ls = mcp.tool(name="service_ls")(ServiceTools.ls)
