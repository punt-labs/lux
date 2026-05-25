"""Connection registry: owns the lazy DisplayClient and reconnect policy.

Single process-wide ``ClientRegistry`` instance — the connection registry
the Hub maintains for talking to the display server. Holds the
``DisplayClient`` reference, the lock that serializes connect /
reconnect across MCP tool threads and the lifespan task, and the
per-process menu-app registration guard.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Self

from punt_lux.apps.beads import BeadsBrowser
from punt_lux.display_client import DisplayClient

if TYPE_CHECKING:
    from punt_lux.protocol import InteractionMessage

logger = logging.getLogger(__name__)

__all__ = ["ClientRegistry", "client_registry"]


class ClientRegistry:
    """Owns the lazy ``DisplayClient`` and per-process menu registrations.

    Thread-safe: ``_lock`` serializes connect / reconnect across the
    MCP lifespan task and tool threads. ``get()`` is the public entry
    point — callers never touch ``_client`` directly.
    """

    _client: DisplayClient | None
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

    def get(self) -> DisplayClient:
        """Return a connected ``DisplayClient``, creating or reconnecting
        as needed. Holds ``_lock`` to prevent duplicate creation when
        called concurrently from the lifespan thread and MCP tool threads."""
        with self._lock:
            if self._client is None:
                self._client = DisplayClient(name="lux-mcp")
            self._setup_apps(self._client)
            if not self._client.is_connected:
                self._client.connect()
            if not self._client.listener_active:
                self._client.start_listener()
            return self._client

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

    def _setup_apps(self, client: DisplayClient) -> None:
        """Register built-in app menu items and callbacks. Idempotent
        per client identity — safe to call on every ``get()`` invocation."""
        if self._apps_registered_for == id(client):
            return
        client.declare_menu_item({"id": "app-beads", "label": "Beads Browser"})
        client.on_event("app-beads", "menu", self._on_beads_browser)
        client._fallback_interaction_handler = self._hub_interaction_fallback
        self._apps_registered_for = id(client)

    @staticmethod
    def _hub_interaction_fallback(msg: InteractionMessage) -> None:
        """Route unmatched interactions through Hub-side element dispatch.

        When the display sends a click InteractionMessage and no
        per-element callback is registered, this fallback resolves
        the element from HubDisplay and fires its registered handlers.
        The handlers were wired by hub_element_factory with a real
        HubPublishSink, so publish decorators reach Hub.publish.
        """
        from punt_lux.domain.element_abc import Element as ElementABC
        from punt_lux.domain.hub import hub_display
        from punt_lux.domain.ids import ClientId, ElementId, SceneId
        from punt_lux.domain.interaction import BUTTON_CLICKED_TOKEN, ButtonClicked

        scene_id = msg.scene_id
        element_id = msg.element_id
        if scene_id is None or element_id is None:
            return
        try:
            element = hub_display.resolve(SceneId(scene_id), ElementId(element_id))
        except (KeyError, LookupError):
            logger.debug(
                "Fallback: element %s not in HubDisplay for scene %s",
                element_id,
                scene_id,
            )
            return
        if not isinstance(element, ElementABC):
            return
        event = ButtonClicked(
            scene_id=SceneId(scene_id),
            element_id=ElementId(element_id),
            owner_id=ClientId("display-fallback"),
            _token=BUTTON_CLICKED_TOKEN,
        )
        element.fire(event)

    def _on_beads_browser(self, _msg: InteractionMessage) -> None:
        """Open Beads Browser in a daemon thread; log render failures."""
        if (client := self._client) is None:
            logger.warning("_on_beads_browser: client is None, ignoring menu click")
            return

        def _render() -> None:
            try:
                BeadsBrowser().render(client)
            except Exception:
                logger.exception("BeadsBrowser.render failed in background thread")

        threading.Thread(target=_render, daemon=True).start()


client_registry = ClientRegistry()
