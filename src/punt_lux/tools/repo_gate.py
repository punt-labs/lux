"""Apply checkout activation to repository-bound MCP sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from punt_lux.hub.lifecycle import disconnect_connection
from punt_lux.tools import tools as core
from punt_lux.tools._repo_selection import RepoSelection

if TYPE_CHECKING:
    import mcp_types as mt
    from fastmcp.tools.base import ToolResult

    from punt_lux.service.repo_activation import ActivationState


class RepoGate(Middleware):
    """Leave standalone MCP clients alone; do no work for an off checkout."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if context.message.name in {"enablement", "status"}:
            return await call_next(context)
        state = await self._off_state(context)
        if state is None:
            return await call_next(context)
        self._disconnect()
        msg = f"{state.describe()}. Run /lux enable or lux enable in that checkout."
        raise ToolError(msg)

    @staticmethod
    async def _off_state(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ActivationState | None:
        scope = core.scope()
        identity = core.OPERATIONS.identity_of(scope=scope)
        declared = (context.message.arguments or {}).get("repo")
        selection = RepoSelection(context.fastmcp_context)
        return await selection.off_state(declared, identity)

    @staticmethod
    def _disconnect() -> None:
        scope = core.scope()
        if core.OPERATIONS.identity_of(scope=scope) is not None:
            core.OPERATIONS.drop_session(scope.connection_id)
            disconnect_connection(scope.connection_id)
