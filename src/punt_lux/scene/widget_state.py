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

    def discard_for(self, element_id: str) -> None:
        """Drop a removed element's own bare-id key across a whole-root re-push.

        Only the exact ``element_id`` key is removed, never a prefix/suffix match:
        a string heuristic cannot decide whether ``btn_ok`` belongs to ``btn`` or
        to ``btn_ok`` while ids may contain the ``_`` separator, so any such match
        risks wiping a survivor's transient state (selection, scroll, in-progress
        text) — the exact loss A6 exists to prevent. A removed element's decorated
        keys (``{id}__open``, ``__tbl_sel_{id}``) linger harmlessly and are
        re-seeded on the next ``ensure`` for that id.
        """
        self.discard(element_id)

    def clear(self) -> None:
        self._state.clear()
