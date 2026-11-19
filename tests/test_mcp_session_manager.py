"""Tests for the MCP SDK boundary in the Lux HTTP session manager."""

from __future__ import annotations

import pytest
from mcp.server.context import ServerRequestContext
from mcp.server.session import ServerSession
from mcp_types.version import LATEST_HANDSHAKE_VERSION

from punt_lux.mcp_session_manager import LuxSessionManager


def test_missing_sdk_connection_fails_closed() -> None:
    """An SDK upgrade must not let Lux run a session without cleanup."""
    ctx = ServerRequestContext[object](
        session=ServerSession.__new__(ServerSession),
        lifespan_context=None,
        protocol_version=LATEST_HANDSHAKE_VERSION,
        method="initialize",
    )

    with pytest.raises(RuntimeError, match="no longer exposes the connection"):
        LuxSessionManager._sdk_connection(ctx)
