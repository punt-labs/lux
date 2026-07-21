"""MenuOperations — menus are Hub-owned; the replicator pushes every change.

These tests encode the third correction: set_menu and register_menu_item write
the Hub menu registry and hand the composed bar to the replicator (the sole
writer), never reaching the display directly. A spy replicator records the
marks, proving there is no second writer. list_menus reads the registry and
round-trips the separator sentinel through the typed model.
"""

from __future__ import annotations

from typing import Self

from punt_lux.client_label import ClientLabel
from punt_lux.domain.hub.menu_models import Menu, MenuAction, MenuSeparator
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations.menus import MenuOperations
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.menu_results import MenuList, Ok, SetMenuRequest
from punt_lux.operations.models.register_tool import RegisterToolRequest
from punt_lux.operations.scope import Scope


class _MenuMarkerSpy:
    """A DirtyMarker counting the payload-less menu flags — nothing else touched."""

    _flags: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._flags = 0
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        raise AssertionError("a menu write must not mark a scene dirty")

    def mark_cleared(self) -> None:
        raise AssertionError("a menu write must not mark a clear")

    def mark_menus(self) -> None:
        self._flags += 1

    @property
    def pushed(self) -> int:
        """How many times a menu push was flagged."""
        return self._flags


def test_set_menu_writes_the_registry_and_pushes_via_the_replicator() -> None:
    registry = HubMenuRegistry()
    marker = _MenuMarkerSpy()
    ops = MenuOperations(registry, marker)

    request = SetMenuRequest.parse(
        [{"label": "File", "items": [{"label": "Run", "id": "run"}]}]
    )
    result = ops.set_menu(request)

    assert isinstance(result, Ok)
    # The agent bar landed in the registry as a typed model, and exactly one push
    # was marked — the replicator is the only writer.
    assert any(m.label == "File" for m in registry.menu_bar())
    assert marker.pushed == 1


def test_register_menu_item_scopes_to_the_connection_and_pushes() -> None:
    registry = HubMenuRegistry()
    marker = _MenuMarkerSpy()
    ops = MenuOperations(registry, marker)

    result = ops.register_menu_item(
        RegisterToolRequest(tool_id="build", label="Build"),
        scope=Scope(ConnectionId("c1")),
    )

    # The item lands in the registered (World-menu) items, not the agent bar.
    assert isinstance(result, Ok)
    assert any(i.id == "build" for i in registry.registered_items())
    assert registry.menu_bar() == []
    assert marker.pushed == 1


def test_register_menu_item_passes_a_parse_error_through_without_pushing() -> None:
    # A never-raising parse: an empty tool_id is rejected as an OpError the
    # adapter renders, and no push is flagged because nothing was registered.
    registry = HubMenuRegistry()
    marker = _MenuMarkerSpy()
    ops = MenuOperations(registry, marker)

    result = ops.register_menu_item(
        RegisterToolRequest.parse(
            tool_id="", label="Nameless", shortcut=None, icon=None
        ),
        scope=Scope(ConnectionId("c1")),
    )

    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "tool_id" in result.reason
    assert registry.registered_items() == []
    assert marker.pushed == 0


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


def test_drop_session_forgets_items_and_re_pushes_so_no_stale_menu_lingers() -> None:
    # The stale-menu-on-disconnect regression: dropping a session must mark a
    # push, or the display keeps showing the departed session's World-menu items
    # until the next unrelated menu write.
    registry = HubMenuRegistry()
    marker = _MenuMarkerSpy()
    ops = MenuOperations(registry, marker)
    scope = Scope(ConnectionId("c1"))
    ops.register_menu_item(RegisterToolRequest(tool_id="x", label="X"), scope=scope)

    ops.drop_session(scope)

    # The registry is emptied AND a second push is flagged — the drop replicates,
    # so the worker's next fresh read of the registry finds no items to send.
    assert registry.registered_items() == []
    assert marker.pushed == 2


def test_list_menus_reports_the_display_applications_composition() -> None:
    # The read must match the screen: registered items render under Applications
    # → the client's submenu (luxd's label), items sorted by label — not an
    # invented "Tools" group.
    registry = HubMenuRegistry()
    ops = MenuOperations(registry, _MenuMarkerSpy())
    conn = Scope(ConnectionId("c1"))
    ops.register_menu_item(RegisterToolRequest(tool_id="z", label="Zebra"), scope=conn)
    ops.register_menu_item(RegisterToolRequest(tool_id="a", label="Apple"), scope=conn)

    menus = ops.list_menus().menus

    apps = next(m for m in menus if m.label == "Applications")
    submenu = apps.items[0]
    assert isinstance(submenu, Menu)
    assert submenu.label == ClientLabel.of(ClientLabel.LUX)  # "Lux"
    # Items are sorted by label, matching the display's own ordering.
    labels = [i.label for i in submenu.items if isinstance(i, MenuAction)]
    assert labels == ["Apple", "Zebra"]


def test_list_menus_keeps_an_action_labelled_like_the_separator() -> None:
    # An action carrying an id survives round-trip as an action even when its
    # label is the "---" sentinel — discrimination is on the id, not the label.
    registry = HubMenuRegistry()
    ops = MenuOperations(registry, _MenuMarkerSpy())
    ops.set_menu(
        SetMenuRequest.parse(
            [{"label": "Edit", "items": [{"label": "---", "id": "dash"}]}]
        )
    )

    menu = next(m for m in ops.list_menus().menus if m.label == "Edit")
    assert isinstance(menu.items[0], MenuAction)
    assert menu.items[0].id == "dash"
