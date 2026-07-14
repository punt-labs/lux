"""Per-scene key-value store for interactive widget state across ImGui frames."""

from __future__ import annotations

from typing import Any, ClassVar, Self


class WidgetState:
    """Key-value store for interactive widget state across ImGui frames."""

    # Suffixes of the tab-bar suppression slots (per-render-session, reset on a
    # re-push). Honoured = the active tab a frame last force-selected (echo);
    # pending = the tab a ``TabChanged`` is outstanding for (fire suppression).
    HONOURED_SUFFIX: ClassVar[str] = ":active_honoured"
    PENDING_SUFFIX: ClassVar[str] = ":active_pending"
    _SESSION_SUFFIXES: ClassVar[tuple[str, ...]] = (HONOURED_SUFFIX, PENDING_SUFFIX)

    # Suffix of an input_text's honoured-value slot: the text last reconciled
    # with the Hub. Kept off ``_SESSION_SUFFIXES`` so a re-push does NOT reset
    # it — the user's in-progress buffer and its honoured record must survive a
    # whole-UI resend; only element removal (``discard_for``) clears it.
    INPUT_HONOURED_SUFFIX: ClassVar[str] = ":input_honoured"

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
        """Discard a removed element's key, dialog latches, and tab-bar slots.

        Each key is built from the id, never a substring match, so a survivor
        like ``btn_ok`` is never wiped. Clearing the dialog latches lets a
        re-added same-id dialog reopen; clearing the honoured and pending slots
        lets a re-added same-id tab bar re-honour the Hub active tab rather than
        firing a spurious ``TabChanged`` off a stale value. A removed table's
        selection/filter keys linger until scene clear (cosmetic).
        """
        if not element_id:
            return
        self.discard(element_id)
        self.discard(f"{element_id}__open")
        self.discard(f"{element_id}__dismissed")
        self.discard(f"{element_id}{self.HONOURED_SUFFIX}")
        self.discard(f"{element_id}{self.PENDING_SUFFIX}")
        self.discard(f"{element_id}{self.INPUT_HONOURED_SUFFIX}")

    def reset_honoured(self) -> None:
        """Discard every tab-bar suppression slot, keeping durable user state.

        A re-push restarts each tab bar's render session, so the tab it last
        force-selected and the tab it last fired for must both be forgotten:
        the next frame re-honours the Hub selection instead of firing a spurious
        ``TabChanged`` off a stale value, and the pending slot no longer gags a
        genuine later switch. Selection, scroll, and text survive the re-push.
        """
        self._state = {
            key: value
            for key, value in self._state.items()
            if not key.endswith(self._SESSION_SUFFIXES)
        }

    def clear(self) -> None:
        self._state.clear()
