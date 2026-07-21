"""HubMenuRegistry — the Hub-owned menu bar and per-session tool items.

Menus are UI the agent submits, and the Hub is the authority for submitted UI.
This registry holds the authoritative menu state as typed models so
``list_menus`` reads it with no reach-around and the replicator pushes it like
any scene. ``set_menus`` replaces the agent-defined bar; ``register_item`` keys a
tool item by id, last write winning across sessions so the registry never holds
two items with one id, and the owning session's disconnect drops it.

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

from punt_lux.domain.hub.menu_models import Menu, MenuAction, MenuState

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
        """Register a tool item, keyed by id, last write winning across sessions.

        The id belongs to whichever session wrote it last: registering an id any
        session already holds moves it to the caller, so the registry keeps one
        item per id and agrees with the display's own dedupe by construction —
        ``registered_items`` and the push can no longer diverge from the screen.
        The owning session's disconnect is what removes it (see ``drop``).
        """
        with self._lock:
            self._discard_id(action.id)
            self._tool_items.setdefault(connection_id, []).append(action)

    def _discard_id(self, item_id: str) -> None:
        """Remove ``item_id`` from whichever session holds it. Caller holds the lock.

        The one-item-per-id invariant means at most one session matches; a session
        left with no items is pruned so ``registered_items`` and ``drop`` stay tidy.
        """
        for connection_id in list(self._tool_items):
            items = self._tool_items[connection_id]
            remaining = [item for item in items if item.id != item_id]
            if len(remaining) == len(items):
                continue
            if remaining:
                self._tool_items[connection_id] = remaining
            else:
                del self._tool_items[connection_id]
            return

    def drop(self, connection_id: ConnectionId) -> None:
        """Forget a departed session's tool items. No-op if absent.

        A session only holds the ids it wrote most recently, so a disconnect
        removes exactly those — an id another session later claimed has already
        moved away and is untouched.
        """
        with self._lock:
            self._tool_items.pop(connection_id, None)

    def menu_bar(self) -> list[Menu]:
        """Return a deep copy of the agent-defined menu bar (the display's bar).

        ``frozen=True`` blocks field reassignment but not mutation of ``Menu.items``
        (a list), so the stored models are deep-copied out — a caller cannot reach
        back through a returned menu and mutate registry state after the lock.
        """
        with self._lock:
            return [menu.model_copy(deep=True) for menu in self._menus]

    def registered_items(self) -> list[MenuAction]:
        """Return a deep copy of every session's tool items, flattened.

        Copied for the same reason as ``menu_bar``: a read never hands out a
        stored model a caller could mutate, so isolation is uniform across the
        registry's read surface rather than a per-type judgement.
        """
        with self._lock:
            return [
                item.model_copy(deep=True)
                for items in self._tool_items.values()
                for item in items
            ]

    def wire_snapshot(self) -> MenuState:
        """Return the whole menu state as wire payloads, composed under one lock.

        The replicator reads this fresh at send time, so the snapshot is the
        registry's state at that instant — the read-at-send discipline that makes
        a stale menu push impossible (there is no payload to go stale). ``to_wire``
        builds new dicts and lists, so — unlike ``menu_bar``/``registered_items``
        before their deep copies — this read never aliased a stored model.
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
