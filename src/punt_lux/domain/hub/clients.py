"""Connection registry: owns the lazy DisplayLink and reconnect policy.

Single process-wide ``ClientRegistry`` instance — the connection registry
the Hub maintains for talking to the display server. Holds the
``DisplayLink`` reference, the lock that serializes connect /
reconnect across MCP tool threads and the lifespan task, and the
per-process menu-app registration guard.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Self

from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.hub_interaction_dispatch import HubInteractionDispatch

logger = logging.getLogger(__name__)

__all__ = ["ClientRegistry", "client_registry"]

# What luxd calls itself on the one socket connection it holds to the display.
_DISPLAY_CLIENT_NAME = "lux-mcp"


class ClientRegistry:
    """Owns the lazy ``DisplayLink`` and per-process menu registrations.

    Thread-safe: ``_lock`` serializes connect / reconnect across the
    MCP lifespan task and tool threads. ``get()`` is the public entry
    point — callers never touch ``_client`` directly.
    """

    _client: DisplayLink | None
    _lock: threading.RLock
    _apps_registered_for: int | None

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._client = None
        self._lock = threading.RLock()
        self._apps_registered_for = None
        return self

    @property
    def lock(self) -> threading.RLock:
        """Return the registry lock so adapters can serialize their own
        per-session bookkeeping against connect / reconnect."""
        return self._lock

    def get(self) -> DisplayLink:
        """Return a connected ``DisplayLink``, creating or reconnecting
        as needed. Holds ``_lock`` to prevent duplicate creation when
        called concurrently from the lifespan thread and MCP tool threads."""
        with self._lock:
            if self._client is None:
                self._client = DisplayLink(name=_DISPLAY_CLIENT_NAME)
            self._setup_apps()
            if not self._client.is_connected:
                self._client.connect()
            if not self._client.listener_active:
                self._client.start_listener()
            return self._client

    def drop(self) -> None:
        """Close the current client so the next ``get`` binds a fresh connection.

        The replicator calls this after a send fails: closing the dead socket
        makes ``get`` reconnect on the next send rather than reuse a stale fd.
        """
        with self._lock:
            if self._client is not None:
                self._client.close()

    def with_reconnect[T](self, fn: Callable[[], T]) -> T:
        """Run ``fn``; on ``OSError`` close, reconnect, restart listener, retry once."""
        try:
            return fn()
        except OSError as exc:
            logger.info(
                "Connection lost (%s), reconnecting to display",
                type(exc).__name__,
            )
            with self._lock:
                if self._client is not None:
                    self._client.close()
                    try:
                        self._client.connect()
                        self._client.start_listener()
                    except (OSError, RuntimeError) as reconnect_exc:
                        msg = f"Reconnect failed after connection loss: {reconnect_exc}"
                        raise RuntimeError(msg) from exc
                return fn()

    def _setup_apps(self) -> None:
        """Wire the Hub-side dispatch for display clicks. Idempotent per client.

        Beads is no longer a Hub-side built-in: each session registers its own
        Beads menu callback and services clicks from its repo shell, so this only
        installs the D21 fallback that routes every display interaction back
        through Hub-side element dispatch. Reads ``self._client``, which ``get``
        ensures is bound before calling.
        """
        client = self._client
        if client is None or self._apps_registered_for == id(client):
            return
        client.set_fallback_handler(HubInteractionDispatch.dispatch)
        self._apps_registered_for = id(client)


client_registry = ClientRegistry()
