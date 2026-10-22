"""Tests for HubParts -- the collaborators a HubDisplay hands out, each wired live."""

from __future__ import annotations

from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.protocol.elements.text import TextElement

_CONN = ConnectionId("c1")
_SCENE = SceneId("s1")


def test_the_lifecycle_and_the_clients_registry_share_one_registration() -> None:
    parts = HubDisplay().parts
    parts.lifecycle.arrive(_CONN)
    assert parts.clients.session_of(_CONN) is not None


def test_a_departure_through_the_lifecycle_empties_the_registry() -> None:
    parts = HubDisplay().parts
    parts.lifecycle.arrive(_CONN)
    parts.lifecycle.depart(_CONN)
    assert parts.clients.session_of(_CONN) is None


def test_reads_see_what_the_display_installed() -> None:
    display = HubDisplay()
    display.parts.lifecycle.arrive(_CONN)
    display.replace_scene(_CONN, _SCENE, [TextElement(id="t1", content="x")])
    assert display.parts.reads.element_count(_SCENE) == 1


def test_the_reader_lists_a_live_scene_until_it_is_quarantined() -> None:
    display = HubDisplay()
    display.parts.lifecycle.arrive(_CONN)
    display.replace_scene(_CONN, _SCENE, [TextElement(id="t1", content="x")])
    assert display.parts.reader.replicable_scene_ids() == (_SCENE,)


def test_the_parts_are_the_same_objects_on_every_read() -> None:
    display = HubDisplay()
    assert display.parts is display.parts
