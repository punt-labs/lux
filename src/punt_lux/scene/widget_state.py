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
        return self._state.setdefault(element_id, default)

    def discard(self, element_id: str) -> None:
        """Remove ``element_id`` from the cache; no-op if absent."""
        self._state.pop(element_id, None)

    def discard_for(self, element_id: str) -> None:
        """Discard a removed element's key and its open/dismiss latches.

        Removes exactly ``element_id``, ``{element_id}__open`` and
        ``{element_id}__dismissed`` — built from the id, never a substring match,
        so a survivor like ``btn_ok`` is never wiped. Clearing the latches lets a
        re-added same-id dialog reopen: ``dialog.begin`` reads
        ``ensure(dismiss_key, CLOSED)`` and ``ensure`` seeds only an absent key,
        so a stale ``OPEN`` latch would leave it dismissed. A removed table's
        ``__tbl_sel_{id}`` / ``__tbl_search_{fidx}_{id}`` keys embed the id at the
        end, so they linger until scene clear — a re-added same-id table shows
        stale selection/filter (cosmetic, not a functional break).
        """
        if not element_id:
            return
        self.discard(element_id)
        self.discard(f"{element_id}__open")
        self.discard(f"{element_id}__dismissed")

    def clear(self) -> None:
        self._state.clear()
