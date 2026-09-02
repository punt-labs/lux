"""The menu boundary: what the display accepts from the Hub, and what it refuses.

The Hub sends menus over a socket, and a socket carries whatever the sender put
on it. Before this check existed, a payload whose ``items`` was not a list took
out everything downstream of it: composing the model raised, so the whole menu
bar went blank for the frame, and ``list_menus`` raised, so the introspection
query answered nothing at all rather than answering about the menus that were
fine.

These tests hold the boundary to three promises: a well-formed menu is kept
whole, a malformed one is refused and named where it lands, and a refusal costs
its own menu and nothing else.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from punt_lux.display.menus.wire import (
    WireAction,
    WireMenu,
    WireSeparator,
)
from punt_lux.display.menus.wire_field import WireField
from punt_lux.domain.hub.menu_models import MenuAction
from punt_lux.domain.hub.session_callback import CallbackInvocation, SessionCallback
from punt_lux.domain.ids import ConnectionId

_BAR: dict[str, Any] = {
    "label": "File",
    "items": [{"label": "Open", "id": "file.open"}, {"label": "---"}],
}
_CLIENTS: dict[str, Any] = {
    "label": "Clients",
    "items": [{"label": "lux", "items": [{"label": "Beads", "id": "c1\x1fbeads"}]}],
}
# The payload that used to take the whole bar, and the whole query, with it.
_ITEMS_NOT_A_LIST: dict[str, Any] = {"label": "voxd", "items": 7}


def _checked(payload: object) -> WireMenu:
    """Return the menu a payload describes, raising if it is malformed."""
    return WireMenu.of_payload(payload, field=WireField("menus"))


class TestWhatIsAccepted:
    """The shapes the Hub sends all arrive intact."""

    def test_a_menu_keeps_its_label_and_entries_in_order(self) -> None:
        menu = _checked(_BAR)

        assert menu.label == "File"
        assert [entry.label for entry in menu.entries] == ["Open", "---"]

    def test_an_action_carries_what_a_click_needs(self) -> None:
        item = {"label": "Quit", "id": "q", "shortcut": "^Q"}
        action = _checked({"label": "File", "items": [item]}).entries[0]

        assert isinstance(action, WireAction)
        assert (action.label, action.item_id, action.shortcut) == ("Quit", "q", "^Q")
        assert action.enabled is True

    def test_an_action_may_be_sent_disabled(self) -> None:
        item = {"label": "Close", "id": "c", "enabled": False}
        action = _checked({"label": "File", "items": [item]}).entries[0]

        assert isinstance(action, WireAction)
        assert action.enabled is False

    def test_a_separator_is_a_line_with_nothing_to_click(self) -> None:
        rule = _checked(_BAR).entries[1]

        assert isinstance(rule, WireSeparator)
        assert (rule.label, rule.item_id) == ("---", "")

    def test_a_nested_menu_stays_a_menu(self) -> None:
        client = _checked(_CLIENTS).entries[0]

        assert isinstance(client, WireMenu)
        assert client.label == "lux"

    def test_a_menu_with_no_items_key_holds_no_entries(self) -> None:
        assert _checked({"label": "File"}).entries == ()

    def test_a_field_the_display_does_not_render_is_ignored(self) -> None:
        """The Hub sends an icon; the display has nowhere to put one yet."""
        item = {"label": "Open", "id": "o", "icon": "folder"}
        menu = _checked({"label": "File", "items": [item]})

        assert [entry.label for entry in menu.entries] == ["Open"]

    def test_an_action_may_carry_the_frame_it_owns(self) -> None:
        item = {"label": "Beads", "id": "beads", "frame_id": "beads-lux"}
        action = _checked({"label": "Clients", "items": [item]}).entries[0]

        assert isinstance(action, WireAction)
        assert action.frame_id == "beads-lux"

    def test_an_action_with_no_frame_owns_none(self) -> None:
        item = {"label": "Details", "id": "d"}
        action = _checked({"label": "Clients", "items": [item]}).entries[0]

        assert isinstance(action, WireAction)
        assert action.frame_id is None


class TestWhatIsRefused:
    """A malformed payload is refused where it lands, and says where it was."""

    @pytest.mark.parametrize(
        ("payload", "loc"),
        [
            (7, "menus"),
            ("File", "menus"),
            ({"items": []}, "menus.label"),
            ({"label": "", "items": []}, "menus.label"),
            ({"label": 7, "items": []}, "menus.label"),
            ({"label": "voxd", "items": 7}, "menus.items"),
            ({"label": "voxd", "items": "Open"}, "menus.items"),
            ({"label": "voxd", "items": [7]}, "menus.items.0"),
            (
                {"label": "voxd", "items": [{"label": "Open", "id": 7}]},
                "menus.items.0.id",
            ),
            (
                {"label": "voxd", "items": [{"label": "Open", "id": ""}]},
                "menus.items.0.id",
            ),
            ({"label": "voxd", "items": [{"id": "o"}]}, "menus.items.0.label"),
            ({"label": "voxd", "items": [{"label": "Open"}]}, "menus.items.0.label"),
            (
                {
                    "label": "voxd",
                    "items": [{"label": "Open", "id": "o", "shortcut": 7}],
                },
                "menus.items.0.shortcut",
            ),
            (
                {
                    "label": "voxd",
                    "items": [{"label": "Open", "id": "o", "enabled": 1}],
                },
                "menus.items.0.enabled",
            ),
            (
                {
                    "label": "voxd",
                    "items": [{"label": "Open", "id": "o", "frame_id": 7}],
                },
                "menus.items.0.frame_id",
            ),
        ],
    )
    def test_a_malformed_field_is_refused_by_name(
        self, payload: object, loc: str
    ) -> None:
        with pytest.raises(ValueError, match=f"^{loc}: expected "):
            _checked(payload)

    def test_a_malformed_entry_deep_in_a_nest_names_its_place(self) -> None:
        nested = {
            "label": "Clients",
            "items": [{"label": "lux", "items": [{"label": "Beads", "id": 7}]}],
        }

        with pytest.raises(ValueError, match=r"^menus\.items\.0\.items\.0\.id: "):
            _checked(nested)


class TestAcceptingWhatArrives:
    """A send of many menus keeps the good ones and logs the rest."""

    def test_every_well_formed_menu_is_kept_in_order(self) -> None:
        held = WireMenu.accepted([_BAR, _CLIENTS], origin="agent_menus")

        assert [menu.label for menu in held] == ["File", "Clients"]

    def test_a_malformed_menu_costs_itself_and_nothing_else(self) -> None:
        held = WireMenu.accepted([_ITEMS_NOT_A_LIST, _BAR], origin="callback_menus")

        assert [menu.label for menu in held] == ["File"]

    def test_a_refusal_names_the_menu_and_the_field(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.ERROR):
            WireMenu.accepted([_BAR, _ITEMS_NOT_A_LIST], origin="callback_menus")

        assert "Rejected a replicated menu" in caplog.text
        assert "callback_menus.1.items: expected a list" in caplog.text

    def test_nothing_sent_is_held_as_nothing(self) -> None:
        assert WireMenu.accepted([], origin="agent_menus") == ()


class TestWalkingTheLines:
    """Every line, with the menus it sits under — what the inventory reports."""

    def test_a_flat_menus_lines_sit_under_it(self) -> None:
        lines = list(_checked(_BAR).lines())

        assert [(path, line.label) for path, line in lines] == [
            (("File",), "Open"),
            (("File",), "---"),
        ]

    def test_a_nested_line_carries_every_menu_above_it(self) -> None:
        lines = list(_checked(_CLIENTS).lines())

        assert [(path, line.item_id) for path, line in lines] == [
            (("Clients", "lux"), "c1\x1fbeads")
        ]

    def test_a_menu_with_no_entries_walks_to_nothing(self) -> None:
        assert list(_checked({"label": "File"}).lines()) == []


class TestTheFrameIdRoundTrip:
    """A callback's frame ownership survives Hub → wire → Display, or is absent."""

    def test_a_registered_frame_survives_the_hub_to_wire_boundary(self) -> None:
        callback = SessionCallback(id="beads", label="Beads", frame_id="beads-lux")
        action = MenuAction(
            id=CallbackInvocation(ConnectionId("lux"), callback.id).menu_id,
            label=callback.label,
            frame_id=callback.frame_id,
        )

        menu = _checked({"label": "Clients", "items": [action.to_wire()]})

        (wire_action,) = menu.entries
        assert isinstance(wire_action, WireAction)
        assert wire_action.frame_id == "beads-lux"

    def test_no_registered_frame_survives_as_none(self) -> None:
        callback = SessionCallback(id="details", label="Details")
        action = MenuAction(
            id=CallbackInvocation(ConnectionId("lux"), callback.id).menu_id,
            label=callback.label,
            frame_id=callback.frame_id,
        )

        menu = _checked({"label": "Clients", "items": [action.to_wire()]})

        (wire_action,) = menu.entries
        assert isinstance(wire_action, WireAction)
        assert wire_action.frame_id is None
