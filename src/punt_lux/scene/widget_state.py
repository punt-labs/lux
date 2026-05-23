"""Per-scene key-value store for interactive widget state across ImGui frames."""

from __future__ import annotations

from typing import Any, Self


class WidgetState:
    """Key-value store for interactive widget state across ImGui frames."""

    _state: dict[str, Any]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._state = {}
        return self

    def get(self, element_id: str, default: Any = None) -> Any:
        return self._state.get(element_id, default)

    def set(self, element_id: str, value: Any) -> None:
        self._state[element_id] = value

    def ensure(self, element_id: str, default: Any) -> Any:
        if element_id not in self._state:
            self._state[element_id] = default
        return self._state[element_id]

    def discard(self, element_id: str) -> None:
        """Remove ``element_id`` from the cache; no-op if absent.

        Used when a patch invalidates cached widget state and the next
        ``ensure(element_id, fresh_default)`` call should re-seed from
        the element's current fields rather than read stale data.
        """
        self._state.pop(element_id, None)

    def clear(self) -> None:
        self._state.clear()

    def clear_suffix(self, suffix: str) -> None:
        """Remove all keys ending with *suffix*."""
        keys = [k for k in self._state if k.endswith(suffix)]
        for k in keys:
            del self._state[k]
