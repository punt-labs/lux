"""Apply checkout activation to repository-bound MCP sessions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

import anyio
import mcp_types as mt
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp.shared.exceptions import MCPError

from punt_lux.hub.lifecycle import disconnect_connection
from punt_lux.service.repo_activation import ActivationState, Checkout
from punt_lux.tools import tools as core

if TYPE_CHECKING:
    from fastmcp import Context
    from fastmcp.tools.base import ToolResult

_ROOT = "lux:repo-root"


class RepoGate(Middleware):
    """Leave standalone MCP clients alone; do no work for an off checkout."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if context.message.name in {"enablement", "status"}:
            return await call_next(context)
        if (state := await self._off_state(context)) is None:
            return await call_next(context)
        scope = core.scope()
        if core.OPERATIONS.identity_of(scope=scope) is not None:
            core.OPERATIONS.drop_session(scope.connection_id)
            disconnect_connection(scope.connection_id)
        msg = f"{state.describe()}. Run /lux enable or lux enable in that checkout."
        raise ToolError(msg)

    async def _off_state(
        self, context: MiddlewareContext[mt.CallToolRequestParams]
    ) -> ActivationState | None:
        root = await self._client_root(context.fastmcp_context)
        for checkout in (root, self._declared_checkout(context)):
            if checkout is not None and not (state := checkout.state()).enabled:
                return state
        return None

    @staticmethod
    def _declared_checkout(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> Checkout | None:
        declared = (context.message.arguments or {}).get("repo")
        if isinstance(declared, str) and (checkout := Checkout.find(Path(declared))):
            return checkout
        identity = core.OPERATIONS.identity_of(scope=core.scope())
        return (
            Checkout.find(Path(identity.repo)) if identity and identity.repo else None
        )

    @staticmethod
    def _local_root(uri: str) -> Checkout | None:
        url = urlsplit(uri)
        if url.scheme == "file" and url.netloc in {"", "localhost"}:
            return Checkout.find(Path(unquote(url.path)))
        return None

    @staticmethod
    async def _client_root(ctx: Context | None) -> Checkout | None:
        if ctx is None or ctx.request_context is None:
            return None
        remembered: object = await ctx.get_state(_ROOT)
        if isinstance(remembered, str):
            return Checkout(Path(remembered))
        caps = ctx.session.client_capabilities
        if remembered or caps is None or caps.roots is None:
            return None
        return await RepoGate._probe(ctx)

    @staticmethod
    async def _probe(ctx: Context) -> Checkout | None:
        checkout = await RepoGate._discover(ctx)
        await ctx.set_state(_ROOT, str(checkout.root) if checkout else True)
        return checkout

    @staticmethod
    async def _discover(ctx: Context) -> Checkout | None:
        with anyio.move_on_after(1):
            try:
                roots = await ctx.session.send_request(
                    mt.ListRootsRequest(), mt.ListRootsResult
                )
            except MCPError:
                return None
            for root in roots.roots:
                if checkout := RepoGate._local_root(str(root.uri)):
                    return checkout
        return None
