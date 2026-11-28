"""Retain an MCP declaration while its Hub registration is dormant."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from fastmcp.exceptions import ToolError

from punt_lux.hub.lifecycle import disconnect_connection
from punt_lux.tools._repo_selection import RepoSelection

if TYPE_CHECKING:
    import mcp_types as mt
    from fastmcp import Context
    from fastmcp.server.middleware import CallNext, MiddlewareContext
    from fastmcp.tools.base import ToolResult

    from punt_lux.operations.facade import Operations
    from punt_lux.wire.model.client_identity import ClientIdentity
    from punt_lux.wire.model.scope import Scope

_DORMANT_IDENTITY = "lux:dormant-identity"


class RepoSession:
    _operations: Operations
    _scope: Scope
    __slots__ = ("_operations", "_scope")

    def __new__(cls, operations: Operations, scope: Scope) -> Self:
        self = super().__new__(cls)
        self._operations = operations
        self._scope = scope
        return self

    async def call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        session = self._session_context(context)
        active = self._operations.identity_of(scope=self._scope)
        saved = await self._saved(session) if active is None else None
        selected = active.repo if active is not None else (saved or {}).get("repo")
        declared = (context.message.arguments or {}).get("repo")
        state = await RepoSelection(session).off_state(declared, selected)
        if state is not None:
            await self._suspend(session, active)
            msg = f"{state.describe()}. Run /lux enable or lux enable in that checkout."
            raise ToolError(msg)
        identifying = context.message.name == "session_identify"
        if saved is not None and not identifying and declared is None:
            self._operations.identify(saved, scope=self._scope)
            await self._forget(session)
        result = await call_next(context)
        if identifying:
            await self._forget(session)
        return result

    @staticmethod
    def _session_context(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> Context | None:
        ctx = context.fastmcp_context
        return ctx if ctx is not None and ctx.request_context is not None else None

    @staticmethod
    async def _saved(session: Context | None) -> dict[str, object] | None:
        if session is None:
            return None
        saved: dict[str, object] | None = await session.get_state(_DORMANT_IDENTITY)
        return saved

    @staticmethod
    async def _forget(session: Context | None) -> None:
        if session is not None:
            await session.delete_state(_DORMANT_IDENTITY)

    async def _suspend(
        self, session: Context | None, active: ClientIdentity | None
    ) -> None:
        if active is None:
            return
        if session is not None:
            await session.set_state(_DORMANT_IDENTITY, active.model_dump(mode="json"))
        self._operations.drop_session(self._scope.connection_id)
        disconnect_connection(self._scope.connection_id)
