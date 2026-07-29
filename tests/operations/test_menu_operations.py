"""MenuOperations — the agent menu bar is Hub-owned; the replicator pushes it.

set_menu writes the Hub menu registry and hands the composed bar to the
replicator (the sole writer), never reaching the display directly. A spy
replicator records the marks, proving there is no second writer. list_menus
reads the registry and round-trips the separator sentinel through the typed
model, then appends the session-then-callback submenus.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Self, final

import pytest
from pydantic import ValidationError

from punt_lux.domain.hub.menu_models import Menu, MenuAction, MenuSeparator
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.ids import SceneId
from punt_lux.operations.menus import MenuOperations
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.menu_results import MenuList, Ok, SetMenuRequest


@final
class _CallbackMenus:
    """A CallbackMenuSource returning fixed submenus — the callback model's side."""

    _menus: list[Menu]

    def __new__(cls, menus: Sequence[Menu] = ()) -> Self:
        self = super().__new__(cls)
        self._menus = list(menus)
        return self

    def callback_menus(self) -> list[Menu]:
        return list(self._menus)


class _MenuMarkerSpy:
    """A DirtyMarker counting the payload-less menu flags — nothing else touched."""

    _flags: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._flags = 0
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        raise AssertionError("a menu write must not mark a scene dirty")

    def mark_menus(self) -> None:
        self._flags += 1

    @property
    def pushed(self) -> int:
        """How many times a menu push was flagged."""
        return self._flags


def test_set_menu_writes_the_registry_and_pushes_via_the_replicator() -> None:
    registry = HubMenuRegistry()
    marker = _MenuMarkerSpy()
    ops = MenuOperations(registry, marker, _CallbackMenus())

    request = SetMenuRequest.parse(
        [{"label": "File", "items": [{"label": "Run", "id": "run"}]}]
    )
    result = ops.set_menu(request)

    assert isinstance(result, Ok)
    # The agent bar landed in the registry as a typed model, and exactly one push
    # was marked — the replicator is the only writer.
    assert any(m.label == "File" for m in registry.menu_bar())
    assert marker.pushed == 1


def test_set_menu_rejects_a_menu_with_a_missing_label() -> None:
    # A menu with no label is rejected by name, not coerced to a blank bar entry.
    result = SetMenuRequest.parse([{"items": [{"label": "Run", "id": "run"}]}])
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.label" in result.reason


def test_set_menu_rejects_a_menu_with_an_empty_label() -> None:
    result = SetMenuRequest.parse([{"label": "", "items": []}])
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.label" in result.reason


def test_menu_rejects_direct_construction_with_a_blank_label() -> None:
    # The model itself forbids a blank label; from_wire is not the only guard.
    with pytest.raises(ValidationError):
        Menu(label="", items=[])


def test_set_menu_rejects_a_menu_whose_items_is_not_a_list() -> None:
    # A present-but-non-list items value is rejected by name, not coerced to [].
    result = SetMenuRequest.parse([{"label": "File", "items": 123}])
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.items" in result.reason


def test_set_menu_rejects_a_menu_whose_items_is_a_string() -> None:
    # A string is a Sequence but never a menu item list — reject, do not iterate it.
    result = SetMenuRequest.parse([{"label": "File", "items": "oops"}])
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.items" in result.reason


def test_set_menu_accepts_a_menu_with_no_items_key() -> None:
    # A missing items key is the one absence that defaults to an empty menu.
    result = SetMenuRequest.parse([{"label": "File"}])
    assert isinstance(result, SetMenuRequest)
    assert result.menus[0].items == []


def test_set_menu_rejects_an_action_item_with_a_missing_label() -> None:
    # An id present but no label is a half-formed action, not a blank menu item.
    result = SetMenuRequest.parse([{"label": "File", "items": [{"id": "run"}]}])
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.items.0.label" in result.reason


def test_set_menu_rejects_an_action_item_with_a_non_string_label() -> None:
    result = SetMenuRequest.parse(
        [{"label": "File", "items": [{"id": "run", "label": 123}]}]
    )
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.items.0.label" in result.reason


def test_set_menu_rejects_an_action_item_with_a_non_string_id() -> None:
    result = SetMenuRequest.parse(
        [{"label": "File", "items": [{"id": 7, "label": "Run"}]}]
    )
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.items.0.id" in result.reason


def test_list_menus_round_trips_the_separator_sentinel() -> None:
    registry = HubMenuRegistry()
    ops = MenuOperations(registry, _MenuMarkerSpy(), _CallbackMenus())
    ops.set_menu(
        SetMenuRequest.parse(
            [
                {
                    "label": "File",
                    "items": [{"label": "Open", "id": "open"}, {"label": "---"}],
                }
            ]
        )
    )

    result = ops.list_menus()

    assert isinstance(result, MenuList)
    menu = next(m for m in result.menus if m.label == "File")
    # The "---" wire sentinel decodes to a typed separator, never a magic label.
    assert isinstance(menu.items[1], MenuSeparator)


def test_list_menus_appends_the_callback_submenus_after_the_agent_bar() -> None:
    # The read reports both parts side by side: the agent bar first, then the
    # session-then-callback submenus the callback model contributes.
    registry = HubMenuRegistry()
    callback_submenu = Menu(
        label="vox — /w/vox", items=[MenuAction(id="c", label="Beads")]
    )
    ops = MenuOperations(registry, _MenuMarkerSpy(), _CallbackMenus([callback_submenu]))
    ops.set_menu(SetMenuRequest.parse([{"label": "File", "items": []}]))

    labels = [menu.label for menu in ops.list_menus().menus]
    assert labels == ["File", "vox — /w/vox"]


def test_list_menus_keeps_an_action_labelled_like_the_separator() -> None:
    # An action carrying an id survives round-trip as an action even when its
    # label is the "---" sentinel — discrimination is on the id, not the label.
    registry = HubMenuRegistry()
    ops = MenuOperations(registry, _MenuMarkerSpy(), _CallbackMenus())
    ops.set_menu(
        SetMenuRequest.parse(
            [{"label": "Edit", "items": [{"label": "---", "id": "dash"}]}]
        )
    )

    menu = next(m for m in ops.list_menus().menus if m.label == "Edit")
    assert isinstance(menu.items[0], MenuAction)
    assert menu.items[0].id == "dash"
