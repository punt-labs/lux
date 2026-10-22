"""Tests for the keyed lookups HubReads and SceneReader answer through a HubDisplay."""

from __future__ import annotations

import pytest

from punt_lux.domain.hub.element_index import UnknownElementError
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.quarantine_record import QuarantineRecord
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.protocol.elements.text import TextElement

_CONN = ConnectionId("c1")
_SCENE = SceneId("s1")
_ROOT = ElementId("t1")


def _display_with_one_root() -> HubDisplay:
    display = HubDisplay()
    display.parts.lifecycle.arrive(_CONN)
    display.replace_scene(_CONN, _SCENE, [TextElement(id="t1", content="hi")])
    return display


class TestStoreLookups:
    def test_an_installed_element_resolves(self) -> None:
        display = _display_with_one_root()
        assert display.parts.reads.resolve(_SCENE, _ROOT).id == _ROOT

    def test_an_installed_element_reports_its_owner(self) -> None:
        display = _display_with_one_root()
        assert display.parts.reads.owner_of(_SCENE, _ROOT) == _CONN

    def test_an_uninstalled_element_has_no_owner_to_report(self) -> None:
        display = _display_with_one_root()
        with pytest.raises(UnknownElementError):
            display.parts.reads.owner_of(_SCENE, ElementId("nope"))

    def test_a_connection_lists_the_elements_it_installed(self) -> None:
        display = _display_with_one_root()
        assert display.parts.reads.elements_owned_by(_CONN) == ((_SCENE, _ROOT),)

    def test_a_quarantined_scene_is_live_for_introspection_only(self) -> None:
        display = _display_with_one_root()
        display.parts.quarantines.quarantine(
            _SCENE, QuarantineRecord(death_count=2, last_death_at=1.0)
        )
        assert display.parts.reader.replicable_scene_ids() == ()
        assert display.parts.reader.live_scene_ids() == (_SCENE,)

    def test_a_registered_connection_is_a_client(self) -> None:
        display = _display_with_one_root()
        assert display.parts.clients.session_of(_CONN) is not None

    def test_an_unregistered_connection_is_not_a_client(self) -> None:
        clients = _display_with_one_root().parts.clients
        assert clients.session_of(ConnectionId("other")) is None
