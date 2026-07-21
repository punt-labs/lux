"""HubMenuRegistry — the Hub-owned menu bar and per-session tool items.

Menus are UI the agent submits, and the Hub is the authority for submitted UI.
This registry holds the authoritative menu state so ``list_menus`` reads it with
no reach-around and the replicator pushes it like any scene. ``set_menus``
replaces the agent-defined bar; ``register_item`` adds a tool item scoped to the
registering session, so a session's items can be dropped when it disconnects.

The two kinds of menu state stay distinct, matching the two the display renders:
``menu_bar`` is the agent menu bar (the display's ``MenuMessage`` bar), and
``registered_items`` is the flat set of tool items (the display's World-menu
``RegisterMenuMessage`` items). Keeping them separate preserves the display's
existing layout — the ownership move to the Hub is invisible to the user.

State is guarded by one independent lock. The lock is never held across another
lock or any I/O — tool threads mutate and read the registry, and the composed
payload is handed to the replicator by value — so it is deadlock-free by
construction (a single mutex with no acquisition ordering).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from punt_lux.domain.ids import ConnectionId

__all__ = ["HubMenuRegistry", "hub_menu_registry"]


@final
class HubMenuRegistry:
    """The authoritative menu bar plus each session's registered tool items."""

    _lock: threading.Lock
    _menus: list[dict[str, object]]
    _tool_items: dict[ConnectionId, list[dict[str, object]]]
    __slots__ = ("_lock", "_menus", "_tool_items")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._lock = threading.Lock()
        self._menus = []
        self._tool_items = {}
        return self

    def set_menus(self, menus: Sequence[Mapping[str, object]]) -> None:
        """Replace the agent-defined menu bar."""
        with self._lock:
            self._menus = [dict(menu) for menu in menus]

    def register_item(
        self, connection_id: ConnectionId, item: Mapping[str, object]
    ) -> None:
        """Add or replace a session's tool item, keyed by its id."""
        with self._lock:
            items = self._tool_items.setdefault(connection_id, [])
            item_id = item.get("id")
            for index, existing in enumerate(items):
                if item_id is not None and existing.get("id") == item_id:
                    items[index] = dict(item)
                    return
            items.append(dict(item))

    def drop(self, connection_id: ConnectionId) -> None:
        """Forget a departed session's tool items. No-op if absent."""
        with self._lock:
            self._tool_items.pop(connection_id, None)

    def menu_bar(self) -> list[dict[str, object]]:
        """Return the agent-defined menu bar (the display's ``MenuMessage`` bar)."""
        with self._lock:
            return [dict(menu) for menu in self._menus]

    def registered_items(self) -> list[dict[str, object]]:
        """Return every session's tool items, flattened for the World menu."""
        with self._lock:
            return [dict(item) for lst in self._tool_items.values() for item in lst]


# Module-level singleton — the production menu registry. Tests construct their
# own HubMenuRegistry() to keep state isolated.
hub_menu_registry = HubMenuRegistry()
