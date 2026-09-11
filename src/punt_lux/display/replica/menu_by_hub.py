"""Pair a Hub-scoped menu store's entries with the Hub that owns each one.

Split from :mod:`punt_lux.display.replica.replicated_menus` (PY-IC-6): flattening
a ``HubScopedStore[tuple[WireMenu, ...]]`` into ``(hub, menu)`` pairs is the one
routing primitive both the agent-defined bar and the ``Clients`` menu need
identically, so it is written once here rather than duplicated per bar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.display.menus.wire import WireMenu
    from punt_lux.domain.hub_id import HubId
    from punt_lux.domain.hub_scoped_store import HubScopedStore

__all__ = ["menus_by_hub"]


def menus_by_hub(
    store: HubScopedStore[tuple[WireMenu, ...]],
) -> Iterator[tuple[HubId, WireMenu]]:
    """Yield every entry of ``store``, each menu paired with its owning Hub.

    The routing primitive a scene-less (menu-sourced) click resolves its one
    target Hub through, once callback and agent menus are Hub-scoped (W3).
    """
    for key, menus in store.entries():
        for menu in menus:
            yield key.hub, menu
