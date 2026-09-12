"""Deliver an agent menu-item click to the owning MCP session's inbox.

An agent's ``menu_set`` item is not a callback with a held listen leg — it is an
agent-in-the-loop notification: "the user selected the item you own; act on it on
your next turn." This module lands that notification as a reserved ``lux.menu``
:class:`ObserverMessage` on the owner's existing per-connection inbox, the same
inbox ``recv()`` drains for Agent Subscribe — so no new standing MCP tool is
added, and no ``topic_subscribe`` is required to receive it.

:class:`MenuEventRouter` mirrors :class:`~punt_lux.domain.hub.callback_hold.
CallbackRouter`'s discipline: it reads the live sessions first (the client
registry's own lock, released before anything else), then delivers via a sink
that never resurrects a dropped inbox. Neither lock is ever held across the other,
so the enqueue reuses the exact acquisition order the callback leg already proves —
introducing no new lock and no new ordering (the design's z-spec tripwire stays
untripped).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Self, cast, final

from punt_lux.protocol.messages.observer import ObserverMessage

if TYPE_CHECKING:
    from punt_lux.domain.hub.callback_ports import LiveSessions
    from punt_lux.domain.hub.session_callback import CallbackInvocation
    from punt_lux.domain.ids import ConnectionId

__all__ = ["MenuDelivery", "MenuEventRouter", "MenuEventSink", "MenuSelection"]

# The Hub-reserved topic a menu selection is delivered under, distinct from any
# agent-declared topic so it is self-identifying and cannot collide.
MENU_TOPIC = "lux.menu"

# A menu event lands on the owner's live inbox, or the owner is gone.
MenuDelivery = Literal["delivered", "provider_gone"]

# Put a message on an existing inbox, returning whether one was present to take it.
type MenuEventSink = Callable[[ConnectionId, ObserverMessage], bool]


@final
@dataclass(frozen=True, slots=True)
class MenuSelection:
    """The user's selection of an agent menu item, as delivered to its owner.

    ``item`` is the agent's own item id (the raw id it registered, recovered from
    the stamped leaf), so the agent reads back the key it chose; ``menu`` is the
    label of the menu the item sits under, carried on the click.
    """

    menu: str
    item: str

    @classmethod
    def of(cls, invocation: CallbackInvocation, value: object) -> Self:
        """Build from a click's parsed invocation and its wire ``value`` payload.

        The item id is the invocation's own (un-stamped) callback id — what the
        agent registered — and the menu label is read off the click value, or left
        empty when the value carries none.
        """
        menu_label = ""
        if isinstance(value, Mapping):
            raw_menu = cast("Mapping[str, object]", value).get("menu")
            if isinstance(raw_menu, str):
                menu_label = raw_menu
        return cls(menu=menu_label, item=invocation.callback_id)

    def observer_message(self) -> ObserverMessage:
        """Render as the reserved ``lux.menu`` event ``recv()`` returns."""
        return ObserverMessage(
            topic=MENU_TOPIC, payload={"menu": self.menu, "item": self.item}
        )


@final
class MenuEventRouter:
    """Deliver a menu selection to the owning live session's inbox, or say why not."""

    _live: LiveSessions
    _sink: MenuEventSink
    __slots__ = ("_live", "_sink")

    def __new__(cls, live: LiveSessions, sink: MenuEventSink) -> Self:
        self = super().__new__(cls)
        self._live = live
        self._sink = sink
        return self

    def deliver(
        self, invocation: CallbackInvocation, selection: MenuSelection
    ) -> MenuDelivery:
        """Land ``selection`` on the owner's inbox if the session is live and has one.

        The live-session read runs first (the client registry's lock, released),
        gating the enqueue exactly as ``CallbackRouter.route`` gates its hold — a
        click for a session gone from the live set is ``provider_gone``, and one
        whose inbox has already been dropped (a listener-only session, or a
        departure that raced the read) finds no sink and is likewise not delivered.
        """
        if invocation.connection_id not in self._live.live_sessions():
            return "provider_gone"
        if self._sink(invocation.connection_id, selection.observer_message()):
            return "delivered"
        return "provider_gone"
