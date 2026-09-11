"""Per-scene widget state, keyed by (Hub, scene id)."""

from __future__ import annotations

from collections import deque
from typing import Self

from punt_lux.display.replica.widget_state import WidgetState, WireScalar
from punt_lux.domain.identity import HubScopedKey, HubScopedStore


class WidgetStateStore:
    """One :class:`WidgetState` per scene, opened and discarded with it --
    Display-only bookkeeping (selection, scroll, in-progress text), keyed by
    :class:`~punt_lux.domain.hub_scoped_key.HubScopedKey` so two Hubs' scenes
    sharing a local id never share one scroll position."""

    _by_scene: HubScopedStore[WidgetState]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._by_scene = HubScopedStore()
        return self

    def __len__(self) -> int:
        return len(self._by_scene)

    def hub_count(self) -> int:
        return self._by_scene.hub_count()

    def open(self, key: HubScopedKey) -> WidgetState:
        """Start and return fresh widget state for a scene new to its frame."""
        state = WidgetState()
        self._by_scene.put(key, state)
        return state

    def get(self, key: HubScopedKey) -> WidgetState | None:
        return self._by_scene.get(key)

    def snapshots(self) -> dict[str, dict[str, WireScalar]]:
        """Every tracked scene's curated snapshot, flattened across Hubs."""
        return {
            key.local: state.observable_snapshot()
            for key, state in self._by_scene.entries()
        }

    def discard(self, key: HubScopedKey) -> None:
        self._by_scene.remove(key)

    def clear(self) -> None:
        """Forget every scene's widget state."""
        self._by_scene = HubScopedStore()

    def retire_elements(self, key: HubScopedKey, stale_ids: set[str]) -> None:
        """Drop only the departed elements' state, then reset the session slots."""
        widget_state = self._by_scene.get(key)
        if widget_state is None:
            return
        deque(map(widget_state.discard_for, stale_ids), maxlen=0)
        widget_state.reset_session_slots()
