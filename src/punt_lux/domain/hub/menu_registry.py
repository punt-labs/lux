"""HubMenuRegistry — the Hub-owned agent menu bar.

Menus are UI the agent submits, and the Hub is the authority for submitted UI.
This registry holds the authoritative agent-defined menu bar as typed models so
``list_menus`` reads it with no reach-around and the replicator pushes it like
any scene. ``set_menus`` replaces the bar; the replicator reads ``wire_snapshot``
fresh at send time so the newest bar always wins.

State is guarded by one independent lock. The lock is never held across another
lock or any I/O — tool threads mutate and read the registry, and the typed state
is handed out as deep copies — so it is deadlock-free by construction (a single
mutex with no acquisition ordering). The class binds no singleton of its own: the
one authoritative instance is built at module scope in ``replicator_instance.py``
and injected at the tools composition root, and the replicator is the sole writer
that pushes its state to the display.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.menu_models import Menu

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ["HubMenuRegistry"]


@final
class HubMenuRegistry:
    """The authoritative agent-defined menu bar."""

    _lock: threading.Lock
    _menus: list[Menu]
    __slots__ = ("_lock", "_menus")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._lock = threading.Lock()
        self._menus = []
        return self

    def set_menus(self, menus: Sequence[Menu]) -> None:
        """Replace the agent-defined menu bar."""
        with self._lock:
            self._menus = list(menus)

    def menu_bar(self) -> list[Menu]:
        """Return a deep copy of the agent-defined menu bar (the display's bar).

        ``frozen=True`` blocks field reassignment but not mutation of ``Menu.items``
        (a list), so the stored models are deep-copied out — a caller cannot reach
        back through a returned menu and mutate registry state after the lock.
        """
        with self._lock:
            return [menu.model_copy(deep=True) for menu in self._menus]

    def wire_snapshot(self) -> tuple[Mapping[str, object], ...]:
        """Return the agent bar as wire payloads, composed under one lock.

        The replicator reads this fresh at send time, so the snapshot is the
        registry's state at that instant — the read-at-send discipline that makes
        a stale menu push impossible (there is no payload to go stale). ``to_wire``
        builds new dicts and lists, so this read never aliases a stored model.
        """
        with self._lock:
            return tuple(menu.to_wire() for menu in self._menus)
