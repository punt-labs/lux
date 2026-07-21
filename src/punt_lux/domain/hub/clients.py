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
from punt_lux.client_label import ClientLabel
from punt_lux.display_client import DisplayClient
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from punt_lux.domain.container_interaction import HeaderToggled, TabChanged
    from punt_lux.domain.interaction import ButtonClicked, ValueChanged
    from punt_lux.protocol import RemoteEventHandlerInvocation

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
                self._client = DisplayClient(name=ClientLabel.LUX)
            self._setup_apps(self._client)
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

    def _setup_apps(self, client: DisplayClient) -> None:
        """Register built-in app menu items and callbacks. Idempotent
        per client identity — safe to call on every ``get()`` invocation."""
        if self._apps_registered_for == id(client):
            return
        client.declare_menu_item({"id": "app-beads", "label": "Beads Browser"})
        client.on_event("app-beads", "menu", self._on_beads_browser)
        client.set_fallback_handler(self._hub_interaction_dispatch)
        self._apps_registered_for = id(client)

    @staticmethod
    @trace
    def _hub_interaction_dispatch(msg: RemoteEventHandlerInvocation) -> None:
        """Route display-side clicks through Hub-side element dispatch.

        D21: the display wraps every handler in ``remote_dispatch``,
        which sends a ``RemoteEventHandlerInvocation`` to the Hub.
        This method receives that message, resolves the element from
        ``HubDisplay``, constructs a ``ButtonClicked`` or
        ``ValueChanged`` depending on ``event_kind``, and fires the
        Hub-side handlers (which have real ``HubPublishSink``).
        """
        from punt_lux.domain.element_abc import Element as ElementABC
        from punt_lux.domain.hub import hub_display
        from punt_lux.domain.ids import ElementId, SceneId

        scene_id = msg.scene_id
        element_id = msg.element_id
        if scene_id is None:
            logger.warning(
                "hub dispatch missing scene_id for element_id=%s",
                element_id,
            )
            return
        try:
            element = hub_display.resolve(SceneId(scene_id), ElementId(element_id))
            owner = hub_display.owner_of(SceneId(scene_id), ElementId(element_id))
        except (KeyError, LookupError) as exc:
            logger.warning(
                "hub dispatch resolve failed scene_id=%s element_id=%s: %s",
                scene_id,
                element_id,
                exc,
            )
            return
        if not isinstance(element, ElementABC):
            logger.warning(
                "hub dispatch type mismatch element_id=%s type=%s",
                element_id,
                type(element).__name__,
            )
            return
        event_kind = msg.event_kind
        event = ClientRegistry._build_hub_event(
            event_kind=event_kind,
            scene_id=scene_id,
            element_id=element_id,
            owner=str(owner),
            value=msg.value,
        )
        if event is None:
            return
        logger.debug(
            "hub dispatch firing element_id=%s scene_id=%s event_kind=%s",
            element_id,
            scene_id,
            event_kind,
        )
        element.fire(event)

        # The handler may have mutated the scene (e.g., a dialog dismissed itself
        # via mark_removed). Mark it dirty; the replicator — the sole writer to
        # the display — resends the whole scene. mark_dirty is queue-only and
        # cannot fail, so a click never blocks on the display.
        from punt_lux.domain.hub.replicator_instance import hub_replicator

        hub_replicator.mark_dirty(SceneId(scene_id))

    @staticmethod
    def _build_hub_event(
        *,
        event_kind: str | None,
        scene_id: str,
        element_id: str,
        owner: str,
        value: object,
    ) -> ButtonClicked | ValueChanged | HeaderToggled | TabChanged | None:
        """Construct the typed event for ``event_kind`` + wire ``value``.

        Returns ``None`` (deny-by-default) when the value has the wrong shape
        for the kind or the kind is unknown — the caller then fires nothing.
        """
        from punt_lux.domain.container_interaction import HeaderToggled, TabChanged
        from punt_lux.domain.ids import ClientId, ElementId, SceneId
        from punt_lux.domain.interaction import ButtonClicked, ValueChanged

        sid, eid, oid = SceneId(scene_id), ElementId(element_id), ClientId(owner)
        if event_kind == "value_changed":
            # A checkbox toggle carries bool, an input_text edit str, a slider
            # drag int/float. The firing element's own setter re-validates the
            # value shape (a slider rejects a non-finite or out-of-range value).
            if not isinstance(value, bool | int | float | str):
                logger.warning("hub dispatch value_changed non-scalar value=%r", value)
                return None
            return ValueChanged(scene_id=sid, element_id=eid, owner_id=oid, value=value)
        if event_kind == "header_toggled":
            if not isinstance(value, bool):
                logger.warning("hub dispatch header_toggled non-bool value=%r", value)
                return None
            return HeaderToggled(
                scene_id=sid, element_id=eid, owner_id=oid, open_=value
            )
        if event_kind == "tab_changed":
            if not isinstance(value, str):
                logger.warning("hub dispatch tab_changed non-str value=%r", value)
                return None
            return TabChanged(scene_id=sid, element_id=eid, owner_id=oid, tab_id=value)
        if event_kind in (None, "button_clicked"):
            return ButtonClicked(scene_id=sid, element_id=eid, owner_id=oid)
        logger.warning("hub dispatch unknown event_kind=%r for %s", event_kind, eid)
        return None

    def _on_beads_browser(self, _msg: RemoteEventHandlerInvocation) -> None:
        """Build the beads board off-thread; it writes the Hub and marks dirty.

        The load runs ``bd`` in a subprocess, so it stays off the listener
        thread. The render itself only mutates the Hub store and signals the
        replicator — no display I/O — so the sole writer to the display is still
        the replicator.
        """

        def _render() -> None:
            try:
                BeadsBrowser().render()
            except Exception:
                logger.exception("BeadsBrowser.render failed in background thread")

        threading.Thread(target=_render, daemon=True).start()


client_registry = ClientRegistry()
