"""Thin MCP transport adapter — the ``_query_tool`` decorator.

The Hub-side connection registry, lock, and reconnect policy live in
``punt_lux.domain.hub``. This module is the MCP-facing decorator that
wraps query-style tools so they short-circuit when the display is not
running, call the Hub-side client registry, and surface query results
as MCP tool returns.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from typing import Any

from punt_lux.domain.hub import client_registry
from punt_lux.paths import DisplayPaths
from punt_lux.tools.server import mcp


def _query_tool(  # pyright: ignore[reportUnusedFunction]  # used in tools.py
    method: str,
    *,
    doc: str = "",
) -> Callable[..., Callable[..., str]]:
    """Wrap a param-builder as a query-based MCP tool."""

    def decorator(fn: Callable[..., dict[str, Any] | None]) -> Callable[..., str]:
        @mcp.tool()
        @functools.wraps(fn)
        def wrapper(**kwargs: Any) -> str:
            if not DisplayPaths().is_running():
                return "not running"
            params = fn(**kwargs) or {}

            def _call() -> str:
                client = client_registry.get()
                response = client.query(method, params)
                if response is None:
                    return "timeout"
                if response.error:
                    return f"error: {response.error}"
                return json.dumps(response.result, indent=2)

            return client_registry.with_reconnect(_call)

        if doc:
            wrapper.__doc__ = doc
        return wrapper

    return decorator
