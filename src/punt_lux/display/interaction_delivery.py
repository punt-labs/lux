"""InteractionDelivery — route queued display interactions back to the Hub.

The display renders a replica and forwards each interaction (a
``RemoteEventHandlerInvocation``) to the Hub that owns the UI. This collaborator
owns that outbound leg: it resolves each event's target client (scene owner, else
broadcast) and sends it under one shared frame deadline, so a slow peer cannot
freeze the render thread per event. Events past the first it cannot send stay the
caller's to re-hold, in order; a held ``modal_closed`` that later ages out of the
buffer is what reverts the optimistic dismiss to Hub truth.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Self

from punt_lux.scene import WidgetState
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.protocol import RemoteEventHandlerInvocation
    from punt_lux.scene import SceneManager
    from punt_lux.socket_server import SocketServer

logger = logging.getLogger(__name__)

__all__ = ["InteractionDelivery"]

# Total time one flush may block the render thread, shared across every send in
# the frame (not per event) so a slow-but-alive peer costs at most this once.
_FRAME_SEND_BUDGET = 1.0


class InteractionDelivery:
    """Send queued display interactions to their owning Hub client.

    Stateless across frames — it holds only the collaborators it routes through
    (the socket server and the scene owner / widget-state lookups). The display
    owns the event queue and calls :meth:`deliver` then :meth:`compensate_evicted`
    each flush.
    """

    _socket_server: SocketServer
    _scene_manager: SceneManager

    def __new__(
        cls,
        *,
        socket_server: SocketServer,
        scene_manager: SceneManager,
    ) -> Self:
        self = super().__new__(cls)
        self._socket_server = socket_server
        self._scene_manager = scene_manager
        return self

    @trace
    def deliver(self, events: Sequence[RemoteEventHandlerInvocation]) -> int:
        """Send events in order under one frame budget; return the count sent.

        Render-thread blocking is capped once per frame by a single deadline taken
        here, not per event. Delivery is a prefix: the moment an event cannot be
        sent — the budget lapsed, the peer is slow, or its client went — that event
        and every one after it stay the caller's to re-hold, in their original order.
        """
        deadline = time.monotonic() + _FRAME_SEND_BUDGET
        for index, event in enumerate(events):
            if time.monotonic() >= deadline:
                return index
            if not self._deliver_one(event, deadline):
                return index
        return len(events)

    def _deliver_one(
        self, event: RemoteEventHandlerInvocation, deadline: float
    ) -> bool:
        """Send one event to its scene owner or broadcast under ``deadline``; landed?

        A menu-bar click carries no ``scene_id``, so it broadcasts to every
        display client — reaching luxd, whose fallback handler resolves the
        callback leaf back to the owning session.
        """
        owner_fd = (
            self._scene_manager.scene_to_owner.get(event.scene_id)
            if event.scene_id
            else None
        )
        if owner_fd is not None:
            target = self._socket_server.fd_to_client.get(owner_fd)
            if target is None:
                return False
            return self._socket_server.send_to_client(target, event, deadline)
        # Broadcast to every client — the list comprehension sends to all before
        # reducing, so one success never short-circuits the rest (a generator in
        # ``any`` would stop at the first delivered send and skip the others).
        sent = [
            self._socket_server.send_to_client(client, event, deadline)
            for client in list(self._socket_server.clients)
        ]
        return any(sent)

    def compensate_evicted(
        self, evicted: Sequence[RemoteEventHandlerInvocation]
    ) -> None:
        """Revert optimistic display state whose interaction never reached the Hub.

        An interaction the buffer evicted (aged or overflowed) never reaches the
        Hub, so the display-side latch it fired optimistically would render forever
        against an unchanged Hub — a modal held shut, a table row held selected.
        Reverting that latch returns the replica to Hub truth. Both cases are the
        same move: drop the latch the lost interaction was speaking for.
        """
        for event in evicted:
            if event.scene_id is None:
                continue
            ws = self._scene_manager.widget_state_for(event.scene_id)
            if ws is None:
                continue
            if event.event_kind == "modal_closed":
                self._revert_modal(ws, event.element_id)
            elif event.event_kind == "row_selection_changed":
                self._revert_row_selection(ws, event.element_id)

    @staticmethod
    def _revert_modal(ws: WidgetState, element_id: str) -> None:
        """Reopen a modal whose optimistic close never reached the Hub."""
        ws.discard(f"{element_id}{WidgetState.OPEN_SUFFIX}")
        ws.discard(f"{element_id}{WidgetState.DISMISS_SUFFIX}")
        logger.warning(
            "reverted modal '%s' dismiss — close was undeliverable", element_id
        )

    @staticmethod
    def _revert_row_selection(ws: WidgetState, element_id: str) -> None:
        """Drop a table's optimistic pending selection that never reached the Hub.

        Without this the pending set renders forever -- the Hub, never told, holds
        the pre-gesture set and a grow-from-empty pick ({} subset of {A}) never
        converges, so no confirming re-push comes.
        """
        ws.discard(f"{element_id}{WidgetState.ROW_SELECTION_PENDING_SUFFIX}")
        ws.discard(f"{element_id}{WidgetState.ROW_SELECTION_HONOURED_SUFFIX}")
        logger.warning(
            "reverted table '%s' selection — change was undeliverable", element_id
        )
