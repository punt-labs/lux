"""MenuStats -- a MenuReplica's menu counts, snapshotted for diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.display.menus.wire import WireMenu

__all__ = ["MenuStats"]


@final
@dataclass(frozen=True, slots=True)
class MenuStats:
    """A point-in-time count of a :class:`~punt_lux.display.replica.menu_replica.
    MenuReplica`'s replicated and Hub-composed menus."""

    agent_menu_count: int
    callback_menu_count: int
    live_hub_count: int

    @property
    def total_menu_count(self) -> int:
        """The total submenu count across agent and callback menus."""
        return self.agent_menu_count + self.callback_menu_count

    @classmethod
    def compute(
        cls,
        agent_menus: Sequence[WireMenu],
        callback_menus: Sequence[WireMenu],
        live_hub_count: int,
    ) -> Self:
        """Snapshot the counts from a MenuReplica's own live menu collections."""
        return cls(len(agent_menus), len(callback_menus), live_hub_count)
