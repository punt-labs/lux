"""Connection registry: owns the lazy DisplayLink and reconnect policy.

Single process-wide: the ``DisplayLink``, its connect/reconnect lock, and
the per-process menu-app guard.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Self

from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.hub_display import hub_display
from punt_lux.domain.hub.hub_interaction_dispatch import HubInteractionDispatch
from punt_lux.domain.hub.null_dirty_marker import NullDirtyMarker
from punt_lux.domain.hub.reconnect_wait import ReconnectWait

if TYPE_CHECKING:
    from punt_lux.domain.hub.replicator_ports import DirtyMarker

logger = logging.getLogger(__name__)

__all__ = ["ClientRegistry", "client_registry"]

# What luxd calls itself on the one socket connection it holds to the display.
_DISPLAY_CLIENT_NAME = "lux-mcp"


class ClientRegistry:
    """Owns the lazy ``DisplayLink`` and per-process menu registrations.

    Thread-safe: ``_lock`` serializes connect/reconnect across the MCP
    lifespan task and tool threads. ``get()`` is the public entry point.
    """

    _client: DisplayLink | None
    _lock: threading.RLock
    _apps_registered_for: int | None
    _marker: DirtyMarker
    _reconnect_gen: int
    _reconnect_cond: threading.Condition
    _stop_requested: bool

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._client = None
        self._lock = threading.RLock()
        self._apps_registered_for = None
        self._marker = NullDirtyMarker()
        self._reconnect_gen = 0
        self._reconnect_cond = threading.Condition(self._lock)
        self._stop_requested = False
        return self

    @property
    def lock(self) -> threading.RLock:
        """Return the lock so adapters serialize their own bookkeeping too."""
        return self._lock

    @property
    def is_connected(self) -> bool:
        """Report a live display connection — cheap, read-only, no I/O."""
        return self._client is not None and self._client.is_connected

    def __repr__(self) -> str:
        return f"ClientRegistry(is_connected={self.is_connected})"

    def attach_replicator(self, marker: DirtyMarker) -> None:
        """Wire the replicator marked dirty after a fresh connect (DES-068)."""
        self._marker = marker

    def get(self) -> DisplayLink:
        """Return a connected ``DisplayLink``, creating/reconnecting as needed;
        holds ``_lock`` against duplicate creation from concurrent callers."""
        with self._lock:
            was_connected = self.is_connected
            client = self._ensure_client()
            self._setup_apps()
            self._ensure_connected(client)
            self._mark_reconnected_if_fresh(was_connected=was_connected)
            return client

    def _ensure_client(self) -> DisplayLink:
        """Create the lazy client on first use; its own service unit supervises."""
        if self._client is None:
            self._client = DisplayLink(
                name=_DISPLAY_CLIENT_NAME, kind="hub", auto_spawn=False
            )
        return self._client

    def _ensure_connected(self, client: DisplayLink) -> None:
        """Connect/reconcile and start the listener, each only if not already."""
        if not client.is_connected:
            self._connect_and_reconcile(client)
        if not client.listener_active:
            client.start_listener()

    def _mark_reconnected_if_fresh(self, *, was_connected: bool) -> None:
        """Bump+notify under ``_lock`` on a not-connected -> connected edge."""
        if not was_connected:
            self._reconnect_gen += 1
            self._reconnect_cond.notify_all()

    @property
    def reconnect_generation(self) -> int:
        """Snapshot BEFORE a dial attempt, so a racing reconnect is caught."""
        with self._lock:
            return self._reconnect_gen

    def wait_for_reconnect(self, wait: ReconnectWait) -> bool:
        """Block for a reconnect or a ``request_stop``; race-free via ``wait_for``."""
        with self._lock:
            return self._reconnect_cond.wait_for(
                lambda: self._reconnect_gen > wait.since_gen or self._stop_requested,
                wait.timeout,
            )

    def request_stop(self) -> None:
        """Wake a parked ``wait_for_reconnect``; latches permanently."""
        with self._lock:
            self._stop_requested = True
            self._reconnect_cond.notify_all()

    def drop(self) -> None:
        """Close the client so the next ``get`` reconnects, not reuses a stale fd."""
        with self._lock:
            if self._client is not None:
                self._client.close()

    def with_reconnect[T](self, fn: Callable[[], T]) -> T:
        """Run ``fn``; on ``OSError`` close, reconnect, restart listener, retry once."""
        try:
            return fn()
        except OSError as exc:
            logger.info("Connection lost (%s), reconnecting", type(exc).__name__)
            try:
                self._reconnect_after_loss()
            except (OSError, RuntimeError) as reconnect_exc:
                msg = f"Reconnect failed after connection loss: {reconnect_exc}"
                raise RuntimeError(msg) from exc
            return fn()

    def _reconnect_after_loss(self) -> None:
        """Close and reconnect the client, holding ``_lock`` for the retry."""
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._connect_and_reconcile(self._client)
                self._client.start_listener()

    def _connect_and_reconcile(self, client: DisplayLink) -> None:
        """Connect a fresh socket, then declare and repaint the Hub's holdings.

        The one choke point every fresh connect runs through (DES-068): the
        manifest is never forgotten, every manifested scene plus the menu is
        marked dirty, and a failed ``send_manifest`` force-closes the link.
        """
        client.connect()
        scene_ids = hub_display.live_scene_ids()
        try:
            client.send_manifest(scene_ids)
        except OSError:
            client.close()
            raise
        for scene_id in scene_ids:
            self._marker.mark_dirty(scene_id)
        self._marker.mark_menus()

    def _setup_apps(self) -> None:
        """Wire the D21 fallback interaction dispatch. Idempotent per client."""
        client = self._ensure_client()
        if self._apps_registered_for == id(client):
            return
        client.set_fallback_handler(HubInteractionDispatch.dispatch)
        self._apps_registered_for = id(client)


client_registry = ClientRegistry()
