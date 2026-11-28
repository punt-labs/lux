"""Apply checkout activation to repository-bound MCP sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from punt_lux.tools import tools as core
from punt_lux.tools._repo_session import RepoSession

if TYPE_CHECKING:
    import mcp_types as mt
    from fastmcp.tools.base import ToolResult


class RepoGate(Middleware):
    """Leave standalone MCP clients alone; do no work for an off checkout."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if self._exempt(context.message.name):
            return await call_next(context)
        return await self._session.call_tool(context, call_next)

    @staticmethod
    def _exempt(name: str) -> bool:
        return name in {"enablement", "status"}

    @property
    def _session(self) -> RepoSession:
        return RepoSession(core.OPERATIONS, core.scope())
