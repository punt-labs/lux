"""The ``/mcp`` request endpoint: session identity and reserved-key refusal."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from starlette.requests import Request
from starlette.responses import Response

from punt_lux.session_key import SessionKey
from punt_lux.tools.server import bind_session, unbind_session

if TYPE_CHECKING:
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.types import Receive, Scope, Send

logger = logging.getLogger(__name__)

__all__ = ["McpAsgiApp"]


@final
class McpAsgiApp:
    """The ``/mcp`` endpoint: resolve the session identity, then serve the request.

    A ``?session_key=`` value becomes the session's :class:`ConnectionId`; a value
    colliding with the reserved REST scope is refused with 403, because sharing it
    would cross scene, menu, and topic ownership and the session's disconnect
    cascade would destroy REST-created state. The identity is bound to the
    calling context before the manager spawns the session's task, so the copied
    task context carries it to the tools and the cleanup cascade.
    """

    _manager: StreamableHTTPSessionManager
    __slots__ = ("_manager",)

    def __new__(cls, manager: StreamableHTTPSessionManager) -> Self:
        self = super().__new__(cls)
        self._manager = manager
        return self

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        session = SessionKey.from_request(
            Request(scope).query_params.get("session_key", "")
        )
        if session.is_reserved:
            logger.warning("Rejected reserved session_key=%s", session.value)
            refusal = Response(
                "session_key is reserved for the REST surface", status_code=403
            )
            await refusal(scope, receive, send)
            return
        token = bind_session(session.value)
        try:
            await self._manager.handle_request(scope, receive, send)
        finally:
            unbind_session(token)
