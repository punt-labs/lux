"""Per-scene widget state, keyed by scene id."""

from __future__ import annotations

from collections import deque
from typing import Self

from punt_lux.display.replica.widget_state import WidgetState, WireScalar


class WidgetStateStore:
    """Hold one :class:`WidgetState` per scene, opened and discarded with it.

    A scene's widget state is the Display's own per-render bookkeeping —
    selection, scroll, in-progress text — so it lives and dies with the scene
    replica rather than with anything the Hub sent.
    """

    _by_scene: dict[str, WidgetState]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._by_scene = {}
        return self

    def __len__(self) -> int:
        """Return the number of scenes holding widget state."""
        return len(self._by_scene)

    def open(self, scene_id: str) -> WidgetState:
        """Start and return fresh widget state for a scene new to its frame."""
        state = WidgetState()
        self._by_scene[scene_id] = state
        return state

    def get(self, scene_id: str) -> WidgetState | None:
        """Return a scene's widget state, or None when it holds none."""
        return self._by_scene.get(scene_id)

    def snapshots(self) -> dict[str, dict[str, WireScalar]]:
        """Return every tracked scene's curated widget-state snapshot, keyed by id."""
        return {
            sid: state.observable_snapshot() for sid, state in self._by_scene.items()
        }

    def discard(self, scene_id: str) -> None:
        """Forget a scene's widget state. No-op when it holds none."""
        self._by_scene.pop(scene_id, None)

    def clear(self) -> None:
        """Forget every scene's widget state."""
        self._by_scene.clear()

    def retire_elements(self, scene_id: str, stale_ids: set[str]) -> None:
        """Drop only the departed elements' state, then reset the session slots."""
        widget_state = self._by_scene.get(scene_id)
        if widget_state is None:
            return
        deque(map(widget_state.discard_for, stale_ids), maxlen=0)
        widget_state.reset_session_slots()
