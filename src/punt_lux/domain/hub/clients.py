"""Connection registry: owns the lazy DisplayLink and reconnect policy.

Single process-wide: the ``DisplayLink``, its connect/reconnect lock, and
the per-process menu-app guard.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.hub_interaction_dispatch import HubInteractionDispatch
from punt_lux.domain.hub.hub_store_factory import hub_display
from punt_lux.domain.hub.null_dirty_marker import NullDirtyMarker
from punt_lux.domain.hub.reconnect_wait import ReconnectWait

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_death import DialDeath
    from punt_lux.domain.hub.dial_ref import DialRef
    from punt_lux.domain.hub.display_requests import DisplayRequests
    from punt_lux.domain.hub.display_writer import WriteSeat
    from punt_lux.domain.hub.replicator_ports import DirtyMarker

__all__ = ["ClientRegistry", "client_registry"]

# What luxd calls itself on the one socket connection it holds to the display.
_DISPLAY_CLIENT_NAME = "lux-mcp"


@final
class ClientRegistry:
    """Owns the lazy ``DisplayLink`` and per-process menu registrations.

    Thread-safe: ``_lock`` serializes connect/reconnect across the MCP
    lifespan task and tool threads. ``asks()`` is the public entry point: it connects
    when needed and hands out the ask port, never the link, so no caller of the
    registry can write to the display or retire a dial but through the registry's
    own verbs.
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
    def is_connected(self) -> bool:
        """Report a live display connection — cheap, read-only, no I/O."""
        return self._client is not None and self._client.is_connected

    def __repr__(self) -> str:
        return f"ClientRegistry(is_connected={self.is_connected})"

    def attach_replicator(self, marker: DirtyMarker) -> None:
        """Wire the replicator marked dirty after a fresh connect (DES-068)."""
        self._marker = marker

    def asks(self) -> DisplayRequests:
        """Connect if needed, then return an ask port pinned to the dial in use.

        Connecting and pinning are one step under ``_lock``, so a drop cannot land
        between them. Raises what the dial or the pin raises when there is no display.
        """
        with self._lock:
            was_connected = self.is_connected
            client = self._ensure_client()
            self._setup_apps()
            self._ensure_connected(client)
            self._mark_reconnected_if_fresh(was_connected=was_connected)
            return client.desk.asks()

    def _ensure_client(self) -> DisplayLink:
        """Create the lazy client on first use; its own service unit supervises."""
        if self._client is None:
            self._client = DisplayLink.to_socket(
                name=_DISPLAY_CLIENT_NAME, kind="hub", auto_spawn=False
            )
        return self._client

    def _ensure_connected(self, client: DisplayLink) -> None:
        """Connect and reconcile if not connected.

        A dial the registry makes starts its reader in the same step
        (``open_as_hub``), so a connected link always has one and
        nothing here waits for the reader slot under the registry lock.
        """
        if not client.is_connected:
            self._connect_and_reconcile(client)

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

    def drop(self, dial: DialRef) -> None:
        """Retire the dial a caller saw fail, unless a redial already replaced it.

        The Hub ends it by its own policy: a sender that finds it gone blames
        nothing on what it was sending.
        """
        with self._lock:
            if self._client is not None:
                self._client.drop_if_current(dial, cause="hub")

    def drop_unresponsive(self, dial: DialRef) -> None:
        """Retire a dial that is open but does not answer, unless a redial replaced it.

        An unanswering dial is evidence about the display, so it is the display's
        end: a sender pinned to it that finds it gone is charged to what it sent.
        """
        with self._lock:
            if self._client is not None:
                self._client.drop_if_current(dial, cause="display")

    def take_death(self) -> DialDeath | None:
        """The oldest display-ended dial not yet charged, handed over once."""
        with self._lock:
            return None if self._client is None else self._client.take_death()

    def take_writer(self) -> WriteSeat:
        """Hand over the display's write seat, once: its holder is the one writer."""
        with self._lock:
            return self._ensure_client().desk.take_seat()

    def _connect_and_reconcile(self, client: DisplayLink) -> None:
        """Connect a fresh socket, then declare and repaint the Hub's holdings.

        The one choke point every fresh connect runs through (DES-068): the link
        declares the manifest inside its own connect step (a manifest that cannot be
        sent closes it), and every manifested scene plus the menu is marked dirty.
        """
        scene_ids = client.open_as_hub(hub_display.live_scene_ids)
        for scene_id in scene_ids:
            self._marker.mark_dirty(scene_id)
        self._marker.mark_menus()

    def _setup_apps(self) -> None:
        """Wire the D21 fallback interaction dispatch. Idempotent per client."""
        client = self._ensure_client()
        if self._apps_registered_for == id(client):
            return
        client.events.set_fallback_handler(HubInteractionDispatch.dispatch)
        self._apps_registered_for = id(client)


client_registry = ClientRegistry()
