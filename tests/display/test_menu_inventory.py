"""MenuInventory — what the display answers when asked what its menu holds.

The Hub reports the menu it composed; this reports the menu the display
received. With the menu nested, a leaf's label no longer says which menu it
belongs to, so every leaf carries the menus it sits under.
"""

from __future__ import annotations

from typing import Any

from punt_lux.display.menus.inventory import MenuInventory

# One flat menu and the nested Clients menu, as the Hub replicates them.
_VOXD: dict[str, Any] = {
    "label": "voxd",
    "items": [{"label": "Music", "id": "v\x1fmusic"}],
}
_CLIENTS: dict[str, Any] = {
    "label": "Clients",
    "items": [
        {"label": "lux", "items": [{"label": "Beads", "id": "c1\x1fbeads"}]},
        {"label": "quarry", "items": [{"label": "Beads", "id": "c2\x1fbeads"}]},
    ],
}
_AGENT_BAR: dict[str, Any] = {
    "label": "File",
    "items": [{"label": "Open", "id": "file.open"}, {"label": "---"}],
}


def _inventory(
    *, agent: list[dict[str, Any]], session: list[dict[str, Any]]
) -> MenuInventory:
    """Return the inventory of what the display holds from both sources."""
    return MenuInventory.of([("agent", agent), ("session", session)])


class TestWhatIsHeld:
    """Every clickable line is reported, at whatever depth it sits."""

    def test_a_top_level_menus_leaves_carry_that_menu(self) -> None:
        inventory = _inventory(agent=[], session=[_VOXD])

        assert [(leaf.path, leaf.label) for leaf in inventory.leaves] == [
            (("voxd",), "Music")
        ]

    def test_a_nested_leaf_carries_every_menu_above_it(self) -> None:
        inventory = _inventory(agent=[], session=[_CLIENTS])

        assert [(leaf.path, leaf.label) for leaf in inventory.leaves] == [
            (("Clients", "lux"), "Beads"),
            (("Clients", "quarry"), "Beads"),
        ]

    def test_two_clients_sharing_a_label_are_told_apart_by_their_path(self) -> None:
        """The label is the same line; the path is what says whose it is."""
        inventory = _inventory(agent=[], session=[_CLIENTS])

        paths = [leaf.path for leaf in inventory.leaves]
        assert len(set(paths)) == 2

    def test_a_separator_is_reported_as_the_line_it_is(self) -> None:
        inventory = _inventory(agent=[_AGENT_BAR], session=[])

        assert [leaf.label for leaf in inventory.leaves] == ["Open", "---"]

    def test_a_menu_with_no_items_contributes_no_leaf(self) -> None:
        inventory = _inventory(agent=[], session=[{"label": "Clients", "items": []}])

        assert inventory.leaves == ()

    def test_nothing_held_is_reported_as_nothing(self) -> None:
        assert _inventory(agent=[], session=[]).leaves == ()


class TestTheReport:
    """The untyped payload an introspection query answers with."""

    def test_each_row_names_its_id_label_path_and_source(self) -> None:
        report = _inventory(agent=[_AGENT_BAR], session=[_CLIENTS]).to_report()

        assert report["menu_items"][0] == {
            "id": "file.open",
            "label": "Open",
            "path": ["File"],
            "source": "agent",
        }
        assert report["menu_items"][2] == {
            "id": "c1\x1fbeads",
            "label": "Beads",
            "path": ["Clients", "lux"],
            "source": "session",
        }

    def test_the_total_counts_every_row(self) -> None:
        report = _inventory(agent=[_AGENT_BAR], session=[_VOXD, _CLIENTS]).to_report()

        assert report["total"] == len(report["menu_items"]) == 5

    def test_an_item_the_hub_sent_no_id_for_reports_an_empty_id(self) -> None:
        """The display has nothing to click with, and says so rather than guessing."""
        bar = {"label": "File", "items": [{"label": "Open"}]}

        report = _inventory(agent=[bar], session=[]).to_report()

        assert report["menu_items"] == [
            {"id": "", "label": "Open", "path": ["File"], "source": "agent"}
        ]
