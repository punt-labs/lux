"""ReplicatedMenus — the agent-defined and Clients (callback) menu bars, each
keyed by :class:`HubScopedKey <punt_lux.domain.identity.HubScopedKey>` so a
second live Hub's push concatenates onto the first's bar instead of erasing
it.

Composed out of :class:`MenuReplica <punt_lux.display.replica.menu_replica.MenuReplica>`
so the replicated-state concern and the two render-surface concerns cluster
around different composed collaborators, rather than one class touching both.
"""

from __future__ import annotations

from itertools import chain
from typing import TYPE_CHECKING, Self, final

from punt_lux.display.menus.wire import WireMenu
from punt_lux.display.replica.menu_stats import MenuStats
from punt_lux.domain.identity import HubId, HubScopedKey, HubScopedStore

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["ReplicatedMenus"]

# One submenu list per Hub -- the disambiguator two Hubs need, for the
# agent-defined bar and the Clients bar alike.
_AGENT_MENUS_LOCAL = "agent_menus"
_CALLBACK_MENUS_LOCAL = "callback_menus"

# replace_callback_menus's own-Hub default; production dispatch always
# resolves and passes the sender's real HubId.
_NO_HUB = HubId.stub()


@final
class ReplicatedMenus:
    """Own the agent-defined and Clients menu bars, both Hub-scoped."""

    _agent_menus: HubScopedStore[tuple[WireMenu, ...]]
    _callback_menus: HubScopedStore[tuple[WireMenu, ...]]
    __slots__ = ("_agent_menus", "_callback_menus")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._agent_menus = HubScopedStore()
        self._callback_menus = HubScopedStore()
        return self

    @property
    def agent_menus(self) -> tuple[WireMenu, ...]:
        """Every live Hub's agent-defined bar, concatenated (not replaced) --
        a second Hub's push used to overwrite the first's outright."""
        return tuple(chain.from_iterable(self._agent_menus.values()))

    def replace_agent_menus(
        self, payloads: Sequence[object], hub: HubId = _NO_HUB
    ) -> None:
        """Take one Hub's agent bar; drops malformed menus. ``hub`` defaults
        to a stub for a caller with no live Hub connection in play."""
        menus = WireMenu.accepted(payloads, origin="agent_menus")
        self._agent_menus.put(HubScopedKey(hub, _AGENT_MENUS_LOCAL), menus)

    @property
    def callback_menus(self) -> tuple[WireMenu, ...]:
        """Every live Hub's ``Clients`` menu, concatenated (not replaced)."""
        return tuple(chain.from_iterable(self._callback_menus.values()))

    def replace_callback_menus(
        self, payloads: Sequence[object], hub: HubId = _NO_HUB
    ) -> None:
        """Take one Hub's ``Clients`` submenus; ``hub`` defaults to a stub."""
        menus = WireMenu.accepted(payloads, origin="callback_menus")
        self._callback_menus.put(HubScopedKey(hub, _CALLBACK_MENUS_LOCAL), menus)

    def forget_hub(self, hub: HubId) -> None:
        """Retire a departed Hub's agent and callback menus, so neither
        lingers as a stale entry."""
        self._agent_menus.drop_hub(hub)
        self._callback_menus.drop_hub(hub)

    @property
    def stats(self) -> MenuStats:
        """This replica's live menu counts, for diagnostics."""
        hub_count = len(self._agent_menus.hubs() | self._callback_menus.hubs())
        return MenuStats.compute(self.agent_menus, self.callback_menus, hub_count)
