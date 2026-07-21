"""MenuOperations — menus are Hub-owned; the replicator pushes every change.

These tests encode the third correction: set_menu and register_menu_item write
the Hub menu registry and hand the composed bar to the replicator (the sole
writer), never reaching the display directly. A spy replicator records the
marks, proving there is no second writer. list_menus reads the registry and
round-trips the separator sentinel through the typed model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Self

from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations.menus import MenuOperations
from punt_lux.operations.models.menu_results import MenuList, Ok, SetMenuRequest
from punt_lux.operations.models.menus import MenuAction, MenuSeparator
from punt_lux.operations.scope import Scope


class _MenuMarkerSpy:
    """A DirtyMarker recording the menu bars pushed — and nothing else touched."""

    _menus: list[Sequence[Mapping[str, object]]]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._menus = []
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        raise AssertionError("a menu write must not mark a scene dirty")

    def mark_cleared(self) -> None:
        raise AssertionError("a menu write must not mark a clear")

    def mark_menus(self, menus: Sequence[Mapping[str, object]]) -> None:
        self._menus.append(menus)

    @property
    def pushed(self) -> list[Sequence[Mapping[str, object]]]:
        return self._menus


def test_set_menu_writes_the_registry_and_pushes_via_the_replicator() -> None:
    registry = HubMenuRegistry()
    marker = _MenuMarkerSpy()
    ops = MenuOperations(registry, marker)

    request = SetMenuRequest.parse(
        [{"label": "Tools", "items": [{"label": "Run", "id": "run"}]}]
    )
    result = ops.set_menu(request)

    assert isinstance(result, Ok)
    # The bar landed in the registry, and exactly one push was marked — the
    # replicator is the only writer.
    assert any(m.get("label") == "Tools" for m in registry.menu_bar())
    assert len(marker.pushed) == 1


def test_register_menu_item_scopes_to_the_connection_and_pushes() -> None:
    registry = HubMenuRegistry()
    marker = _MenuMarkerSpy()
    ops = MenuOperations(registry, marker)

    ops.register_menu_item(
        MenuAction(id="build", label="Build"),
        scope=Scope(ConnectionId("c1")),
    )

    bar = registry.menu_bar()
    tools = next(m for m in bar if m.get("label") == "Tools")
    items = tools["items"]
    assert isinstance(items, list)
    assert any(i.get("id") == "build" for i in items)
    assert len(marker.pushed) == 1


def test_list_menus_round_trips_the_separator_sentinel() -> None:
    registry = HubMenuRegistry()
    ops = MenuOperations(registry, _MenuMarkerSpy())
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


def test_a_dropped_connection_loses_its_items() -> None:
    registry = HubMenuRegistry()
    ops = MenuOperations(registry, _MenuMarkerSpy())
    ops.register_menu_item(
        MenuAction(id="x", label="X"), scope=Scope(ConnectionId("c1"))
    )
    registry.drop(ConnectionId("c1"))
    # With the only session's items gone, the composed bar has no Tools menu.
    assert not any(m.get("label") == "Tools" for m in registry.menu_bar())
