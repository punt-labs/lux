"""Preserve Lux's Hub scope on the SDK connection across HTTP requests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from mcp.server.connection import Connection

from punt_lux.tools.server import (
    bind_session,
    current_client_host,
    current_session,
    unbind_session,
)

if TYPE_CHECKING:
    from contextlib import AsyncExitStack

    from mcp.server.context import CallNext, HandlerResult, ServerRequestContext

__all__ = ["McpSessionScope"]

_CONTACT = "punt_lux.session_contact"


@final
class McpSessionScope:
    """Capture the initializing request's contact and bind it for later calls."""

    _connection: Connection
    __slots__ = ("_connection",)

    def __new__(cls, ctx: ServerRequestContext[object]) -> Self:
        """Resolve the SDK connection associated with the current message."""
        # SDK 2.3 gives middleware no public connection accessor.
        connection = getattr(ctx.session, "_connection", None)
        if not isinstance(connection, Connection):
            msg = "MCP SDK no longer exposes the connection used for Lux cleanup"
            raise RuntimeError(msg)
        self = super().__new__(cls)
        self._connection = connection
        return self

    @property
    def stateful(self) -> bool:
        """Return whether the SDK connection can own persistent Hub state."""
        return self._connection.session_id is not None

    @property
    def initialize_accepted(self) -> bool:
        """Return whether the SDK has accepted the initialization handshake."""
        return self._connection.initialize_accepted

    @property
    def exit_stack(self) -> AsyncExitStack:
        """Return the stack that runs at the end of this SDK connection."""
        return self._connection.exit_stack

    async def dispatch(
        self, ctx: ServerRequestContext[object], call_next: CallNext
    ) -> HandlerResult:
        """Dispatch under the session's contact instead of the message's contact."""
        contact = self._connection.state.get(_CONTACT)
        if contact is None:
            result = await call_next(ctx)
            if ctx.method == "initialize":
                self._connection.state[_CONTACT] = (
                    current_session(),
                    current_client_host(),
                )
            return result
        binding = bind_session(*contact)
        try:
            return await call_next(ctx)
        finally:
            unbind_session(binding)
