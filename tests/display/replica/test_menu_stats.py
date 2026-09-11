"""MenuStats -- value tests for a MenuReplica's snapshotted menu counts."""

from __future__ import annotations

import dataclasses

import pytest

from punt_lux.display.menus.wire import WireMenu
from punt_lux.display.replica.menu_stats import MenuStats


def _menus(*labels: str) -> tuple[WireMenu, ...]:
    return tuple(WireMenu(label, entries=()) for label in labels)


def test_compute_snapshots_the_given_counts() -> None:
    stats = MenuStats.compute(_menus("a", "b"), _menus("c"), live_hub_count=2)

    assert stats.agent_menu_count == 2
    assert stats.callback_menu_count == 1
    assert stats.live_hub_count == 2


def test_compute_counts_empty_collections_as_zero() -> None:
    stats = MenuStats.compute(_menus(), _menus(), live_hub_count=0)

    assert stats.agent_menu_count == 0
    assert stats.callback_menu_count == 0
    assert stats.total_menu_count == 0


def test_total_menu_count_sums_agent_and_callback() -> None:
    stats = MenuStats.compute(_menus("a", "b", "c"), _menus("d"), live_hub_count=1)

    assert stats.total_menu_count == 4


def test_two_snapshots_with_equal_fields_are_equal() -> None:
    a = MenuStats.compute(_menus("a"), _menus("b"), live_hub_count=1)
    b = MenuStats.compute(_menus("a"), _menus("b"), live_hub_count=1)

    assert a == b


def test_is_immutable() -> None:
    stats = MenuStats.compute([], [], live_hub_count=0)

    with pytest.raises(dataclasses.FrozenInstanceError):
        stats.agent_menu_count = 5  # type: ignore[misc]  # frozen dataclass
