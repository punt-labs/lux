"""HubMenuRegistry — the Hub-owned menu bar and per-session tool items.

Menus are UI the agent submits, and the Hub is the authority for submitted UI.
This registry holds the authoritative menu state as typed models so
``list_menus`` reads it with no reach-around and the replicator pushes it like
any scene. ``set_menus`` replaces the agent-defined bar; ``register_item`` adds a
tool item scoped to the registering session, so a session's items can be dropped
when it disconnects.

The two kinds of menu state stay distinct, matching the two the display renders:
``menu_bar`` is the agent menu bar (the display's ``MenuMessage`` bar), and
``registered_items`` is the flat set of tool items (the display's World-menu
``RegisterMenuMessage`` items). Keeping them separate preserves the display's
existing layout — the ownership move to the Hub is invisible to the user.

State is guarded by one independent lock. The lock is never held across another
lock or any I/O — tool threads mutate and read the registry, and the typed state
is handed out by value — so it is deadlock-free by construction (a single mutex
with no acquisition ordering). The registry is constructed at the composition
root and injected; there is no module singleton.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.replicator_ports import MenuState
from punt_lux.operations.models.menus import Menu, MenuAction

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.ids import ConnectionId

__all__ = ["HubMenuRegistry"]


@final
class HubMenuRegistry:
    """The authoritative menu bar plus each session's registered tool items."""

    _lock: threading.Lock
    _menus: list[Menu]
    _tool_items: dict[ConnectionId, list[MenuAction]]
    __slots__ = ("_lock", "_menus", "_tool_items")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._lock = threading.Lock()
        self._menus = []
        self._tool_items = {}
        return self

    def set_menus(self, menus: Sequence[Menu]) -> None:
        """Replace the agent-defined menu bar."""
        with self._lock:
            self._menus = list(menus)

    def register_item(self, connection_id: ConnectionId, action: MenuAction) -> None:
        """Add or replace a session's tool item, keyed by its id."""
        with self._lock:
            items = self._tool_items.setdefault(connection_id, [])
            for index, existing in enumerate(items):
                if existing.id == action.id:
                    items[index] = action
                    return
            items.append(action)

    def drop(self, connection_id: ConnectionId) -> None:
        """Forget a departed session's tool items. No-op if absent."""
        with self._lock:
            self._tool_items.pop(connection_id, None)

    def menu_bar(self) -> list[Menu]:
        """Return the agent-defined menu bar (the display's ``MenuMessage`` bar)."""
        with self._lock:
            return list(self._menus)

    def registered_items(self) -> list[MenuAction]:
        """Return every session's tool items, flattened for the World menu."""
        with self._lock:
            return [item for items in self._tool_items.values() for item in items]

    def wire_snapshot(self) -> MenuState:
        """Return the whole menu state as wire payloads, composed under one lock.

        The replicator reads this fresh at send time, so the snapshot is the
        registry's state at that instant — the read-at-send discipline that makes
        a stale menu push impossible (there is no payload to go stale).
        """
        with self._lock:
            return MenuState(
                bar=tuple(menu.to_wire() for menu in self._menus),
                items=tuple(
                    item.to_wire()
                    for items in self._tool_items.values()
                    for item in items
                ),
            )
