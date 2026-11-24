"""Identity of one live MCP session or applet connection."""

from __future__ import annotations

from typing import NewType

__all__ = ["ConnectionId"]

ConnectionId = NewType("ConnectionId", str)
