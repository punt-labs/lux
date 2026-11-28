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
from punt_lux.service.repo_activation import Checkout
from punt_lux.tools import tools as core

if TYPE_CHECKING:
    from fastmcp import Context
    from fastmcp.tools.base import ToolResult

_ROOT = "lux:repo-root"
_RESOLVED_ROOTS = "lux:resolved-roots"


class RepoGate(Middleware):
    """Leave standalone MCP clients alone; do no work for an off checkout."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if context.message.name in {"enablement", "status"}:
            return await call_next(context)
        checkout = await self._checkout(context)
        if checkout is None:
            return await call_next(context)
        state = checkout.state()
        if state.enabled:
            return await call_next(context)
        scope = core.scope()
        if core.OPERATIONS.identity_of(scope=scope) is not None:
            core.OPERATIONS.drop_session(scope.connection_id)
            disconnect_connection(scope.connection_id)
        msg = f"{state.describe()}. Run /lux enable or lux enable in that checkout."
        raise ToolError(msg)

    async def _checkout(
        self, context: MiddlewareContext[mt.CallToolRequestParams]
    ) -> Checkout | None:
        ctx = context.fastmcp_context
        checkout = self._declared_checkout(context.message.arguments or {})
        if checkout is not None:
            return checkout
        identity = core.OPERATIONS.identity_of(scope=core.scope())
        if identity is not None and identity.repo is not None:
            return Checkout.find(Path(identity.repo))
        if ctx is None or ctx.request_context is None:
            return None
        remembered: object = await ctx.get_state(_ROOT)
        if isinstance(remembered, str):
            return Checkout(Path(remembered))
        return await self._client_root(ctx)

    @staticmethod
    def _declared_checkout(arguments: dict[str, object]) -> Checkout | None:
        declared = arguments.get("repo")
        return Checkout.find(Path(declared)) if isinstance(declared, str) else None

    @staticmethod
    def _local_root(uri: str) -> Checkout | None:
        url = urlsplit(uri)
        if url.scheme == "file" and url.netloc in {"", "localhost"}:
            return Checkout.find(Path(unquote(url.path)))
        return None

    @staticmethod
    async def _should_probe(ctx: Context) -> bool:
        caps = ctx.session.client_capabilities
        return bool(
            caps and caps.roots is not None and not await ctx.get_state(_RESOLVED_ROOTS)
        )

    @staticmethod
    async def _client_root(ctx: Context) -> Checkout | None:
        if not await RepoGate._should_probe(ctx):
            return None
        try:
            with anyio.move_on_after(1):
                roots = await ctx.session.send_request(
                    mt.ListRootsRequest(), mt.ListRootsResult
                )
                for root in roots.roots:
                    checkout = RepoGate._local_root(str(root.uri))
                    if checkout is not None:
                        await ctx.set_state(_ROOT, str(checkout.root))
                        return checkout
        except MCPError:
            pass
        await ctx.set_state(_RESOLVED_ROOTS, value=True)
        return None
