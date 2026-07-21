"""MenuItemRegistry — the display client's local roster of menu items.

Owns the registered agent tool items and the ids declared as built-ins, behind
its own lock so a store, a declare, and a whole agent-item replace stay
consistent under concurrent access. A store dedupes by id — a duplicate updates
in place instead of appending a second entry — and an agent-item replace keeps
every declared built-in and skips any incoming item whose id collides with one,
so the Hub set can never drop or override a built-in.
"""

from __future__ import annotations

import threading
from typing import Any, Self

__all__ = ["MenuItemRegistry"]


class MenuItemRegistry:
    """The registered menu items and the ids declared as built-ins."""

    _items: list[dict[str, Any]]
    _declared_ids: set[str]
    _lock: threading.Lock
    __slots__ = ("_declared_ids", "_items", "_lock")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._items = []
        self._declared_ids = set()
        self._lock = threading.Lock()
        return self

    def _store(self, item: dict[str, Any]) -> None:
        """Add ``item``, or replace one already sharing its id. Caller holds the lock.

        An item whose id matches an existing entry replaces it in place; anything
        else (a new id, or an id-less item) is appended.
        """
        stored = dict(item)
        item_id = item.get("id")
        if item_id is not None:
            for idx, existing in enumerate(self._items):
                if existing.get("id") == item_id:
                    self._items[idx] = stored
                    return
        self._items.append(stored)

    def declare(self, item: dict[str, Any]) -> None:
        """Store a built-in item and remember its id so a replace never drops it."""
        with self._lock:
            self._store(item)
            item_id = item.get("id")
            if isinstance(item_id, str):
                self._declared_ids.add(item_id)

    def replace_agent_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace the agent items, keep declared built-ins, and return the snapshot.

        Each incoming item is stored (dedup by id); one whose id collides with a
        declared built-in is skipped so the agent set can never override it.
        """
        with self._lock:
            self._items = [i for i in self._items if i.get("id") in self._declared_ids]
            for item in items:
                if item.get("id") not in self._declared_ids:
                    self._store(item)
            return list(self._items)

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a copy of the current items for replay to the display."""
        with self._lock:
            return list(self._items)
