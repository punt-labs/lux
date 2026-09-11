"""InteractionDelivery — route queued display interactions to the Hub that
owns each one (scene owner, else declared Hub), never a broadcast. What
cannot be delivered gives up its display-side optimism via ``Compensation``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self

from punt_lux.display.evicted_compensation import CompensationTable
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.display.evictions import Evictions
    from punt_lux.display.replica import SceneReplica
    from punt_lux.display.socket_server import SocketListener
    from punt_lux.protocol import RemoteEventHandlerInvocation

__all__ = ["InteractionDelivery"]

# _deliver_one's outcome: sent; dropped (unroutable -- compensate); deferred
# (Hub absent this instant, perhaps mid-reconnect -- hold without stalling);
# blocked (send budget/socket -- stop the line, retry next frame).
type _SendOutcome = Literal["sent", "dropped", "deferred", "blocked"]
# deliver's report: events to drop from the buffer, then the unroutable subset.
type _Events = tuple[RemoteEventHandlerInvocation, ...]
type _DeliveryReport = tuple[_Events, _Events]


class InteractionDelivery:
    """Send queued display interactions to their owning Hub client.

    Stateless across frames — holds only the collaborators it routes through.
    The display calls :meth:`deliver` then :meth:`compensate_evicted` each flush.
    """

    _socket_listener: SocketListener
    _scenes: SceneReplica

    def __new__(
        cls,
        *,
        socket_listener: SocketListener,
        scenes: SceneReplica,
    ) -> Self:
        self = super().__new__(cls)
        self._socket_listener = socket_listener
        self._scenes = scenes
        return self

    @trace
    def deliver(
        self, events: Sequence[RemoteEventHandlerInvocation]
    ) -> _DeliveryReport:
        """Send events under the frame's budget; return the events to drop and
        the unroutable subset to compensate. ``blocked`` stops the line (retry
        next frame); ``deferred`` is skipped and kept (its Hub may be
        mid-reconnect); ``dropped`` is given up now."""
        removed: list[RemoteEventHandlerInvocation] = []
        dropped: list[RemoteEventHandlerInvocation] = []
        for event in events:
            match self._deliver_one(event):
                case "sent":
                    removed.append(event)
                case "dropped":
                    removed.append(event)
                    dropped.append(event)
                case "deferred":
                    continue
                case "blocked":
                    break
        return tuple(removed), tuple(dropped)

    def _deliver_one(self, event: RemoteEventHandlerInvocation) -> _SendOutcome:
        """Resolve one event's target and send it -- never a broadcast."""
        owner_fd = self._resolve_target(event)
        if owner_fd is None:
            return self._unresolved(event)
        target = self._socket_listener.fd_to_client.get(owner_fd)
        if target is None:
            return "blocked"
        sent = self._socket_listener.send_to_client(target, event)
        return "sent" if sent else "blocked"

    @staticmethod
    def _unresolved(event: RemoteEventHandlerInvocation) -> _SendOutcome:
        """Classify an event with no live target. A menu event (no scene) whose
        Hub token did not resolve may be mid-reconnect -- ``deferred``, so the
        bounded buffer holds it for the reconnect window. Everything else -- a
        scene gone from the replica, an event naming no target -- is ``dropped``."""
        if event.scene_id is None and event.hub_token is not None:
            return "deferred"
        return "dropped"

    def _resolve_target(self, event: RemoteEventHandlerInvocation) -> int | None:
        """Return one event's target fd: its scene's owner, else the Hub its
        ``hub_token`` names -- a menu id resolves only within its own Hub."""
        if event.scene_id:
            return self._scenes.scene_to_owner.get(event.scene_id)
        if event.hub_token is not None:
            return self._socket_listener.fd_for_hub_token(event.hub_token)
        return None

    def compensate_evicted(self, evicted: Evictions) -> None:
        """Revert optimistic display state for every interaction the buffer
        lost (aged, overflowed, or dropped) whose element no newer gesture
        of the same kind is still speaking for -- the next frame then
        renders the Hub's own value instead of a rejection that never came."""
        for event in evicted.compensable:
            self._compensate_one(event)

    def _compensate_one(self, event: RemoteEventHandlerInvocation) -> None:
        """Give up one lost interaction's optimism. A scene-less event (a
        menu click) and one whose scene is gone both have no latch to give
        up: it lives in per-scene widget state, so no scene means none."""
        if event.scene_id is None:
            return
        ws = self._scenes.widget_state_for(event.scene_id)
        if ws is None:
            return
        CompensationTable.for_kind(event.event_kind).revert(ws, event.element_id)
