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
    """Callback: open the Beads Browser in a frame.

    Runs in a daemon thread to avoid blocking the listener thread
    (render_beads_board calls subprocess.run with a 10s timeout).
    """
    if _client is None:
        logger.warning("_on_beads_browser: client is None, ignoring menu click")
        return
    threading.Thread(target=BeadsBrowser().render, args=(_client,), daemon=True).start()


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
    """Run *fn* with one automatic reconnect on socket failure.

    If the display server restarts, the cached socket dies silently —
    ``is_connected`` still returns True because the socket object exists.
    This wrapper catches ``OSError`` (covers broken pipe, connection
    reset, bad file descriptor, etc.), closes the stale socket,
    reconnects the same client instance (preserving accumulated state
    like registered menu items), and retries *fn* exactly once.

    Holds ``_client_lock`` during the close/reconnect sequence to
    prevent races with ``_get_client()`` in other threads.
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
