"""Per-scene key-value store for interactive widget state across ImGui frames."""

from __future__ import annotations

from typing import Any, ClassVar, Self


class WidgetState:
    """Key-value store for interactive widget state across ImGui frames."""

    # Suffix of an echo-suppression key (the tab a tab-bar last force-selected):
    # per-render-session bookkeeping that resets on a re-push, not user state.
    # Held here so the resetters and the tab-bar renderer share one convention.
    HONOURED_SUFFIX: ClassVar[str] = ":active_honoured"

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
        self.discard(f"{element_id}{self.HONOURED_SUFFIX}")

    def reset_honoured(self) -> None:
        """Discard every echo-suppression honoured key, keeping user state.

        A re-push restarts each tab bar's render session, so the tab it last
        force-selected must be forgotten — the next frame re-honours the Hub
        selection rather than firing a spurious ``TabChanged`` off a stale
        value. Only ``HONOURED_SUFFIX`` keys reset; selection, scroll, and
        in-progress text survive for elements that persist across the re-push.
        """
        self._state = {
            key: value
            for key, value in self._state.items()
            if not key.endswith(self.HONOURED_SUFFIX)
        }

    def clear(self) -> None:
        self._state.clear()
