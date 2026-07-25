"""InteractionDelivery — route queued display interactions back to the Hub.

The display renders a replica and forwards each interaction (a
``RemoteEventHandlerInvocation``) to the Hub that owns the UI. This collaborator
owns that outbound leg: for each queued event it resolves the target client
(menu owner, scene owner, or broadcast), sends it, and reports the events that
reached no client. An undeliverable ``modal_closed`` is compensated by reopening
the optimistically-dismissed popup, so the display reverts to Hub truth instead
of silently diverging when the Hub never learns of the close.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, cast

from punt_lux.scene import WidgetState
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.display.menu_manager import MenuManager
    from punt_lux.protocol import RemoteEventHandlerInvocation
    from punt_lux.scene import SceneManager
    from punt_lux.socket_server import SocketServer

logger = logging.getLogger(__name__)

__all__ = ["InteractionDelivery"]


class InteractionDelivery:
    """Send queued display interactions to their owning Hub client.

    Stateless across frames — it holds only the collaborators it routes through
    (the socket server, the menu owner map, and the scene owner / widget-state
    lookups). The display owns the event queue and calls :meth:`deliver` then
    :meth:`revert_modal_dismissals` each flush.
    """

    _socket_server: SocketServer
    _menu_manager: MenuManager
    _scene_manager: SceneManager

    def __new__(
        cls,
        *,
        socket_server: SocketServer,
        menu_manager: MenuManager,
        scene_manager: SceneManager,
    ) -> Self:
        self = super().__new__(cls)
        self._socket_server = socket_server
        self._menu_manager = menu_manager
        self._scene_manager = scene_manager
        return self

    @trace
    def deliver(
        self, events: Sequence[RemoteEventHandlerInvocation]
    ) -> list[RemoteEventHandlerInvocation]:
        """Send each event to its owner or broadcast; return the undelivered.

        An event is undelivered when it reached no client — a failed send or an
        owner whose socket had already gone. The caller compensates for those
        (an optimistic modal dismiss is reverted in ``revert_modal_dismissals``).
        """
        return [ev for ev in events if not self._deliver_one(ev)]

    @staticmethod
    def _is_world_menu(event: RemoteEventHandlerInvocation) -> bool:
        """Return whether ``event`` is a click on the built-in World menu."""
        raw: object = event.value  # wire payload is ``Any``; pin it to ``object``
        if event.action != "menu" or not isinstance(raw, dict):
            return False
        return cast("dict[str, object]", raw).get("menu") == "World"

    def _deliver_one(self, event: RemoteEventHandlerInvocation) -> bool:
        """Send one event to its owning client or broadcast; return if it landed."""
        owner_fd = (
            self._menu_manager.menu_owners.get(event.element_id)
            if self._is_world_menu(event)
            else None
        )
        if owner_fd is None and event.scene_id:
            owner_fd = self._scene_manager.scene_to_owner.get(event.scene_id)
        if owner_fd is not None:
            target = self._socket_server.fd_to_client.get(owner_fd)
            if target is None:
                return False
            return self._socket_server.send_to_client(target, event)
        # Broadcast to every client — the list comprehension sends to all before
        # reducing, so one success never short-circuits the rest (a generator in
        # ``any`` would stop at the first delivered send and skip the others).
        sent = [
            self._socket_server.send_to_client(client, event)
            for client in list(self._socket_server.clients)
        ]
        return any(sent)

    def revert_modal_dismissals(
        self, undelivered: Sequence[RemoteEventHandlerInvocation]
    ) -> None:
        """Reopen any modal whose close never reached the Hub.

        A modal dismiss is optimistic: the renderer latches the popup shut and
        fires ``ModalClosed`` toward the Hub, which owns the authoritative
        remove. When that interaction is undeliverable the Hub still holds the
        modal open, so clearing the display-side open/dismiss latches reverts the
        replica to Hub truth — the popup reopens and a later dismiss re-fires the
        close instead of the tiers silently diverging.
        """
        for event in undelivered:
            if event.event_kind != "modal_closed" or event.scene_id is None:
                continue
            ws = self._scene_manager.widget_state_for(event.scene_id)
            if ws is None:
                continue
            ws.discard(f"{event.element_id}{WidgetState.OPEN_SUFFIX}")
            ws.discard(f"{event.element_id}{WidgetState.DISMISS_SUFFIX}")
            logger.warning(
                "reverted modal '%s' dismiss — close was undeliverable to the Hub",
                event.element_id,
            )
