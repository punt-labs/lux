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
        """Drop every key owned by ``element_id`` so a removed element leaves no
        transient state while a survivor keeps its own across a whole-root re-push.
        """
        doomed = [key for key in self._state if self._owns(key, element_id)]
        for key in doomed:
            del self._state[key]

    @staticmethod
    def _owns(key: str, element_id: str) -> bool:
        """Return whether ``key`` carries ``element_id`` (exact, ``{id}_``, ``_{id}``).

        Renderer keys embed the id as a prefix (``{id}__open``) or suffix
        (``__tbl_sel_{id}``); the ``_`` boundary keeps ``t1`` off ``t10``, and an
        empty id (a separator has none) owns nothing.
        """
        return bool(element_id) and (
            key == element_id
            or key.startswith(f"{element_id}_")
            or key.endswith(f"_{element_id}")
        )

    def clear(self) -> None:
        self._state.clear()
