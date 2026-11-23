"""Tests for Lux's session-scope boundary with the MCP SDK."""

from __future__ import annotations

import pytest
from mcp.server.context import ServerRequestContext
from mcp.server.session import ServerSession
from mcp_types.version import LATEST_HANDSHAKE_VERSION

from punt_lux.hub.mcp_session_scope import McpSessionScope


def test_missing_sdk_connection_fails_closed() -> None:
    """An SDK upgrade must not let Lux run a session without cleanup."""
    ctx = ServerRequestContext[object](
        session=ServerSession.__new__(ServerSession),
        lifespan_context=None,
        protocol_version=LATEST_HANDSHAKE_VERSION,
        method="initialize",
    )

    with pytest.raises(RuntimeError, match="no longer exposes the connection"):
        McpSessionScope(ctx)
