"""Display client connection management and the query-tool decorator."""

from __future__ import annotations

import functools
import json
import logging
import threading
from collections.abc import Callable
from typing import Any

from punt_lux.apps.beads import BeadsBrowser
from punt_lux.display_client import DisplayClient
from punt_lux.paths import DisplayPaths
from punt_lux.protocol import InteractionMessage
from punt_lux.tools.server import mcp

logger = logging.getLogger(__name__)

_client: DisplayClient | None = None
_client_lock = threading.RLock()

_apps_registered_for: int | None = None


def _on_beads_browser(_msg: InteractionMessage) -> None:
    """Open Beads Browser in a daemon thread; log render failures (60s timeout)."""
    if (client := _client) is None:
        logger.warning("_on_beads_browser: client is None, ignoring menu click")
        return

    def _render() -> None:
        try:
            BeadsBrowser().render(client)
        except Exception:
            logger.exception("BeadsBrowser.render failed in background thread")

    threading.Thread(target=_render, daemon=True).start()


def _setup_apps(client: DisplayClient) -> None:
    """Register built-in app menu items and callbacks.

    Idempotent per client identity — safe to call on every
    ``_get_client()`` invocation.
    """
    global _apps_registered_for
    if _apps_registered_for == id(client):
        return
    client.declare_menu_item({"id": "app-beads", "label": "Beads Browser"})
    client.on_event("app-beads", "menu", _on_beads_browser)
    _apps_registered_for = id(client)


def _get_client() -> DisplayClient:
    """Return a connected DisplayClient, creating or reconnecting as needed.

    Thread-safe: holds ``_client_lock`` to prevent duplicate creation
    when called concurrently from the lifespan thread and MCP tool threads.
    """
    global _client
    with _client_lock:
        if _client is None:
            _client = DisplayClient(name="lux-mcp")
        _setup_apps(_client)
        if not _client.is_connected:
            _client.connect()
        if not _client.listener_active:
            _client.start_listener()
        return _client


def _with_reconnect[T](fn: Callable[[], T]) -> T:
    """Run *fn* with one automatic reconnect on ``OSError``.

    Catches socket failures (broken pipe, reset, bad fd), closes the stale
    socket, reconnects the same client instance under ``_client_lock``, and
    retries *fn* exactly once.
    """
    global _client
    try:
        return fn()
    except OSError as exc:
        logger.info("Connection lost (%s), reconnecting to display", type(exc).__name__)
        with _client_lock:
            if _client is not None:
                _client.close()
                try:
                    _client.connect()
                except (OSError, RuntimeError) as reconnect_exc:
                    msg = f"Reconnect failed after connection loss: {reconnect_exc}"
                    raise RuntimeError(msg) from exc
            return fn()


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
                client = _get_client()
                response = client.query(method, params)
                if response is None:
                    return "timeout"
                if response.error:
                    return f"error: {response.error}"
                return json.dumps(response.result, indent=2)

            return _with_reconnect(_call)

        if doc:
            wrapper.__doc__ = doc
        return wrapper

    return decorator
