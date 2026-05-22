"""Tests for ``DomainPump`` — the basics dual-write route.

Focused on the routing predicate.  Display.apply itself is covered by
``tests/domain/test_display.py``; here we verify what the pump decides
to forward.
"""

from __future__ import annotations

import pytest

from punt_lux.display.domain_pump import DomainPump
from punt_lux.domain.display import Display
from punt_lux.domain.ids import ElementId, SceneId
from punt_lux.protocol import (
    ButtonElement,
    SceneMessage,
    SeparatorElement,
    TextElement,
)

_BASICS = (TextElement, SeparatorElement)


@pytest.fixture
def pump() -> DomainPump:
    display = Display()
    client = display.connect_client(name="test-hub")
    return DomainPump(display, client, _BASICS)


def _scene_snapshot_ids(pump: DomainPump, scene_id: SceneId) -> frozenset[ElementId]:
    """Return the ids in the domain snapshot, or empty if no such scene."""
    try:
        return pump._display.snapshot(scene_id).element_ids
    except KeyError:
        return frozenset()


def test_route_adds_basics_elements(pump: DomainPump) -> None:
    msg = SceneMessage(id="s1", elements=[TextElement(id="t1", content="hi")])
    pump.route(msg)
    assert _scene_snapshot_ids(pump, SceneId("s1")) == {ElementId("t1")}


def test_route_skips_mixed_scene(pump: DomainPump) -> None:
    """A non-basics element disqualifies the whole scene from dual-write."""
    msg = SceneMessage(
        id="s1",
        elements=[
            TextElement(id="t1", content="hi"),
            ButtonElement(id="b1", label="ok"),
        ],
    )
    pump.route(msg)
    assert _scene_snapshot_ids(pump, SceneId("s1")) == frozenset()


def test_route_empty_elements_clears_existing_scene(pump: DomainPump) -> None:
    """Copilot CP-2: re-sending an empty scene must drop prior elements.

    Agents clear a frame by re-sending the scene with ``elements=[]``.
    SceneManager handles this by replacing its scene with an empty list,
    so the legacy renderer shows nothing.  The pump must do the same on
    the domain side — otherwise the domain Display retains the prior
    elements and diverges from SceneManager.
    """
    initial = SceneMessage(id="s1", elements=[TextElement(id="t1", content="hi")])
    pump.route(initial)
    assert _scene_snapshot_ids(pump, SceneId("s1")) == {ElementId("t1")}

    cleared = SceneMessage(id="s1", elements=[])
    pump.route(cleared)
    assert _scene_snapshot_ids(pump, SceneId("s1")) == frozenset()


def test_route_empty_elements_on_fresh_scene_is_safe(pump: DomainPump) -> None:
    """Empty re-send for an unseen scene id creates an empty scene, no error."""
    msg = SceneMessage(id="s-new", elements=[])
    pump.route(msg)
    assert _scene_snapshot_ids(pump, SceneId("s-new")) == frozenset()
