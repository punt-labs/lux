"""The field gate refuses every child-bearing field on both write paths.

A structural field carries child Elements, so replacing its value would install a
new child set and evict the old one — work only ``show`` performs. Two seams must
refuse it: the batch ``update`` path (:class:`HubSceneWriter`) and the D21 store
primitive (:meth:`WriteSeam.set_property`). The legacy child-bearing fields are
exactly ``{children, pages, tabs}``; ``tabs`` is the third, easy to miss because
``LegacyTabBarElement`` names its children neither ``children`` nor ``pages``.
"""

from __future__ import annotations

from typing import cast

import pytest

from punt_lux.domain.element import Element
from punt_lux.domain.hub.deferral_errors import StructuralFieldWriteError
from punt_lux.domain.hub.hub_display import HubDisplay, UnknownElementError
from punt_lux.domain.hub.scene_writer import HubSceneWriter
from punt_lux.domain.hub.write_result import WriteRejected
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import AddElement
from punt_lux.protocol.elements import Tab, TabBarElement
from punt_lux.protocol.elements.layout import LegacyTabBarElement

_SCENE = SceneId("gate-scene")
_CONN = ConnectionId("gate-conn")
_TAB_BAR_ID = ElementId("tb")


def _seed_legacy_tab_bar() -> HubDisplay:
    """Install a ``LegacyTabBarElement`` root whose tab holds a legacy child."""
    hub_display = HubDisplay()
    hub_display.register_client(_CONN)
    bar = LegacyTabBarElement(
        id=str(_TAB_BAR_ID),
        tabs=[
            {
                "label": "One",
                "children": [{"id": "old-child", "kind": "slider", "label": "s"}],
            }
        ],
    )
    # The production scene decoder yields legacy elements as ``Element``; the cast
    # mirrors that runtime contract past a codec-signature variance quibble.
    hub_display.apply(
        _CONN,
        AddElement(scene_id=_SCENE, element=cast("Element", bar), parent_id=None),
    )
    return hub_display


def test_update_set_tabs_on_legacy_tab_bar_is_rejected() -> None:
    """A ``set`` of ``tabs`` on a legacy tab_bar root defers to ``show``.

    Without ``tabs`` in the structural set the write would slip past the gate and
    ``dataclasses.replace`` the root's tab list, rebinding only the root — the new
    tab children never installed, the old never evicted. The gate refuses it whole,
    leaving the stored root's tabs untouched.
    """
    hub_display = _seed_legacy_tab_bar()
    writer = HubSceneWriter(hub_display)

    result = writer.apply(
        _CONN,
        _SCENE,
        [
            {
                "id": str(_TAB_BAR_ID),
                "set": {
                    "tabs": [
                        {
                            "label": "New",
                            "children": [{"id": "new-child", "kind": "text"}],
                        }
                    ]
                },
            }
        ],
    )

    assert isinstance(result, WriteRejected)
    assert "tabs" in result.reason
    assert "show" in result.reason

    stored = cast("LegacyTabBarElement", hub_display.resolve(_SCENE, _TAB_BAR_ID))
    assert stored.tabs[0]["label"] == "One"
    with pytest.raises(UnknownElementError):
        hub_display.resolve(_SCENE, ElementId("new-child"))


def test_set_property_structural_field_is_rejected_fail_loud() -> None:
    """The D21 store primitive refuses a structural field before touching storage.

    ``set_property`` is safe today only because no migrated element exposes a
    ``_set_tabs`` setter. The gate makes that safety explicit: a structural field
    can never reach the store primitive, so a later composite gaining a setter
    cannot reopen the desync.
    """
    hub_display = HubDisplay()
    hub_display.register_client(_CONN)
    bar = TabBarElement(
        id=str(_TAB_BAR_ID),
        tabs=(Tab(tab_id="tab-1", label="One", children=()),),
        active_tab="tab-1",
    )
    hub_display.apply(_CONN, AddElement(scene_id=_SCENE, element=bar, parent_id=None))

    with pytest.raises(StructuralFieldWriteError):
        hub_display.write_seam.set_property(_SCENE, _TAB_BAR_ID, "tabs", [])


def test_set_property_non_structural_field_still_applies() -> None:
    """The gate blocks only structural fields — a scalar set still commits."""
    hub_display = HubDisplay()
    hub_display.register_client(_CONN)
    bar = TabBarElement(
        id=str(_TAB_BAR_ID),
        tabs=(
            Tab(tab_id="tab-1", label="One", children=()),
            Tab(tab_id="tab-2", label="Two", children=()),
        ),
        active_tab="tab-1",
    )
    hub_display.apply(_CONN, AddElement(scene_id=_SCENE, element=bar, parent_id=None))

    hub_display.write_seam.set_property(_SCENE, _TAB_BAR_ID, "active_tab", "tab-2")

    stored = hub_display.resolve(_SCENE, _TAB_BAR_ID)
    assert isinstance(stored, TabBarElement)
    assert stored.active_tab == "tab-2"
