"""Hub-side dispatch of display interactions — the D21 return leg.

The display wraps every handler in ``remote_dispatch`` and sends a
:class:`RemoteEventHandlerInvocation` to the Hub. :class:`HubInteractionDispatch`
is where that message lands: it routes a menu launch to the owning session's
callback hold, and everything else to the scene-element fire on the Hub's
authoritative copy. Kept out of the connection registry so "own the display
connection" and "dispatch a display interaction" are each one responsibility.

Closing a frame is not among them. Where a window sits is the Display's own
business (DES-065 R8), so a close reaches the Hub not at all — it used to, and
the Hub answered by deleting the frame's scenes, which is how a window the user
shut came back blank one round trip later.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.tracing import trace

if TYPE_CHECKING:
    from punt_lux.protocol import RemoteEventHandlerInvocation

logger = logging.getLogger(__name__)

__all__ = ["HubInteractionDispatch"]


class HubInteractionDispatch:
    """Route a display-originated interaction to its Hub-side handler."""

    __slots__ = ()

    @staticmethod
    @trace
    def dispatch(msg: RemoteEventHandlerInvocation) -> None:
        """Route one display interaction by its action to the right Hub handler.

        A ``menu`` launches the owning session's callback; everything else fires
        the scene element on its authoritative copy with the real
        ``HubPublishSink``.
        """
        if msg.action == "menu":
            HubInteractionDispatch._dispatch_menu_callback(msg.element_id)
            return
        HubInteractionDispatch._fire_scene_element(msg)

    @staticmethod
    def _fire_scene_element(msg: RemoteEventHandlerInvocation) -> None:
        """Resolve the invocation's element and fire its typed event Hub-side.

        Resolution and its several drop reasons live in
        ``ElementInvocationResolver``; this method is the fire-or-drop decision
        for whatever it hands back. The element builds its own typed event from
        the wire payload (polymorphic dispatch on its ``RemoteDispatchSpec``s); a
        kind the element does not fire is logged and dropped, never fired. The
        handler runs on the Hub's authoritative copy, and the scene is marked
        dirty so the replicator re-sends any mutation it made.
        """
        from punt_lux.domain.hub import hub_display
        from punt_lux.domain.hub.element_invocation_resolver import (
            ElementInvocationResolver,
        )
        from punt_lux.domain.hub.replicator_instance import hub_replicator
        from punt_lux.domain.ids import ClientId
        from punt_lux.domain.interaction_errors import WrongKindError

        resolved = ElementInvocationResolver(hub_display).resolve(msg)
        if resolved is None:
            return
        try:
            event = resolved.element.build_remote_event(
                event_kind=msg.event_kind,
                scene_id=resolved.scene_id,
                owner_id=ClientId(str(resolved.owner)),
                value=msg.value,
            )
        except WrongKindError as exc:
            logger.warning("hub dispatch denied element_id=%s: %s", msg.element_id, exc)
            return
        resolved.element.fire(event)
        # A handler may have mutated the scene; the replicator (the sole display
        # writer) resends it. mark_dirty is queue-only, so a click never blocks.
        hub_replicator.mark_dirty(resolved.scene_id)

    @staticmethod
    def _dispatch_menu_callback(menu_id: str) -> None:
        """Answer a clicked menu leaf: the Hub's own command, or the client's.

        A menu launch carries no scene id and must never be resolved against the
        element index (the drop that made launching fail). The leaf id names the
        owning connection and the command within it. ``Details`` is the Hub's own
        and is answered here; every other command belongs to the client that
        registered it, and the router holds the invocation for that client's
        delivery leg. A malformed or non-callback id, or a click for a departed
        client, is logged, never crashes, and the menu re-pushes.
        """
        from punt_lux.domain.hub.details_instance import hub_client_details
        from punt_lux.domain.hub.replicator_instance import (
            hub_callback_router,
            hub_replicator,
        )
        from punt_lux.domain.hub.session_callback import CallbackInvocation

        try:
            invocation = CallbackInvocation.from_menu_id(menu_id)
        except ValueError:
            logger.info("menu click for a non-callback leaf id=%r; ignoring", menu_id)
            return
        if invocation.is_details:
            hub_client_details.run(invocation.connection_id)
            return
        if hub_callback_router.route(invocation) == "routed":
            return
        logger.info("menu callback %r not delivered; re-pushing menu", menu_id)
        hub_replicator.mark_menus()
