"""Tests for ``DomainPump`` — the native-kind dual-write route.

After commit 5 the pump shrinks to wire-shape triage only — drop
display-chrome actions, drop messages without a scene id, forward
everything else straight to ``Display.interact``. Domain-validation
failures surface as ``InteractionError`` subclasses; the pump catches
them and logs.
"""

from __future__ import annotations

import pytest

from punt_lux.display.domain_pump import DomainPump
from punt_lux.domain.display import Display
from punt_lux.domain.ids import ElementId, SceneId
from punt_lux.protocol import (
    ButtonElement,
    GroupElement,
    SceneMessage,
    SeparatorElement,
    SliderElement,
    TextElement,
)

# Mixed selection covering both the basics and inputs families — every
# class here belongs to the set of kinds with a per-class renderer.
_NATIVE = (TextElement, SeparatorElement, ButtonElement, SliderElement)


@pytest.fixture
def pump() -> DomainPump:
    display = Display()
    client = display.connect_client(name="test-hub")
    return DomainPump(display, client, _NATIVE)


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


def test_route_adds_inputs_elements(pump: DomainPump) -> None:
    """Inputs kinds are native — flow through the pump unchanged."""
    msg = SceneMessage(
        id="s1",
        elements=[
            ButtonElement(id="b1", label="ok"),
            SliderElement(id="sl1", label="vol", value=0.5),
        ],
    )
    pump.route(msg)
    expected = {ElementId("b1"), ElementId("sl1")}
    assert _scene_snapshot_ids(pump, SceneId("s1")) == expected


def test_route_skips_mixed_scene_with_non_native_kind(pump: DomainPump) -> None:
    """A non-native element (e.g. GroupElement) disqualifies the whole scene."""
    msg = SceneMessage(
        id="s1",
        elements=[
            TextElement(id="t1", content="hi"),
            GroupElement(id="g1", children=[]),
        ],
    )
    pump.route(msg)
    assert _scene_snapshot_ids(pump, SceneId("s1")) == frozenset()


def test_route_empty_elements_clears_existing_scene(pump: DomainPump) -> None:
    """Re-sending an empty scene drops prior elements (Copilot CP-2)."""
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


# -- route_interaction removed by D21 ------------------------------------
# Display no longer dispatches interactions locally. The remote_dispatch
# handler on each element sends RemoteEventHandlerInvocations to the Hub, where
# the real handler fires. Tests for the Hub-side dispatch path live in
# tests/domain/test_hub_interaction_dispatch.py.


# frame_close and no-scene-id tests also removed with route_interaction.


def test_route_multiple_anonymous_separators(
    pump: DomainPump, caplog: pytest.LogCaptureFixture
) -> None:
    """Copilot CP-NEW-1: anonymous SeparatorElements must not collide."""
    msg = SceneMessage(
        id="s1",
        elements=[
            SeparatorElement(),
            SeparatorElement(),
            SeparatorElement(),
        ],
    )
    with caplog.at_level("WARNING", logger="punt_lux.display.domain_pump"):
        pump.route(msg)
    assert _scene_snapshot_ids(pump, SceneId("s1")) == {
        ElementId("separator:0"),
        ElementId("separator:1"),
        ElementId("separator:2"),
    }
    assert not caplog.records, (
        f"unexpected DomainPump warnings: {[r.getMessage() for r in caplog.records]}"
    )
