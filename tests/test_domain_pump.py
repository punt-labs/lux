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
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.protocol import (
    ButtonElement,
    GroupElement,
    InteractionMessage,
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


# -- route_interaction ----------------------------------------------------


def test_route_interaction_forwards_button_click_through_display_interact(
    pump: DomainPump,
) -> None:
    """A wire ``InteractionMessage`` lands on the Element's handler registry."""
    button = ButtonElement(id="b1", label="OK")
    pump.route(SceneMessage(id="s1", elements=[button]))

    observed: list[ButtonClicked] = []
    snap = pump._display.snapshot(SceneId("s1"))
    stored = snap.element(ElementId("b1"))
    assert isinstance(stored, ButtonElement)
    stored.add_handler(ButtonClicked, observed.append)

    msg = InteractionMessage(element_id="b1", action="b1", value=True, scene_id="s1")
    pump.route_interaction(msg)

    assert len(observed) == 1
    assert observed[0].element_id == ElementId("b1")


def test_route_interaction_drops_non_button_kinds_without_raising(
    pump: DomainPump,
) -> None:
    """Slider / non-button interactions surface as logged failures, not raises."""
    pump.route(SceneMessage(id="s1", elements=[SliderElement(id="sl1", label="Vol")]))
    msg = InteractionMessage(
        element_id="sl1", action="changed", value=42.0, scene_id="s1"
    )
    # Should not raise — pump catches InteractionError.
    pump.route_interaction(msg)


def test_route_interaction_logs_on_unknown_scene(
    pump: DomainPump, caplog: pytest.LogCaptureFixture
) -> None:
    """A click on a scene the domain Display doesn't know logs and drops."""
    msg = InteractionMessage(
        element_id="b1", action="b1", value=True, scene_id="never-seen"
    )
    with caplog.at_level("WARNING", logger="punt_lux.display.domain_pump"):
        pump.route_interaction(msg)
    messages = [r.getMessage() for r in caplog.records]
    assert any("never-seen" in m for m in messages), messages


def test_route_interaction_logs_on_unknown_element_in_known_scene(
    pump: DomainPump, caplog: pytest.LogCaptureFixture
) -> None:
    """SFH M1: unknown element in a tracked scene is a divergence signal."""
    pump.route(SceneMessage(id="s1", elements=[ButtonElement(id="b1", label="OK")]))
    msg = InteractionMessage(
        element_id="ghost", action="ghost", value=True, scene_id="s1"
    )
    with caplog.at_level("WARNING", logger="punt_lux.display.domain_pump"):
        pump.route_interaction(msg)
    messages = [r.getMessage() for r in caplog.records]
    assert any("ghost" in m for m in messages), messages


def test_route_interaction_skips_menu_action_without_log(
    pump: DomainPump, caplog: pytest.LogCaptureFixture
) -> None:
    """Menu emissions are wire-chrome, not element-targeted — dropped silently."""
    pump.route(SceneMessage(id="s1", elements=[ButtonElement(id="b1", label="OK")]))
    menu_msg = InteractionMessage(
        element_id="menu.file.open",
        action="menu",
        value={"menu": "File", "item": "Open"},
        scene_id="s1",
    )
    with caplog.at_level("WARNING", logger="punt_lux.display.domain_pump"):
        pump.route_interaction(menu_msg)
    assert caplog.records == [], (
        f"menu action must not log; got {[r.getMessage() for r in caplog.records]}"
    )


def test_route_interaction_skips_frame_close_action_without_log(
    pump: DomainPump, caplog: pytest.LogCaptureFixture
) -> None:
    """Frame-close events are display-chrome, not element-targeted."""
    pump.route(SceneMessage(id="s1", elements=[ButtonElement(id="b1", label="OK")]))
    msg = InteractionMessage(element_id="frame-1", action="frame_close", scene_id="s1")
    with caplog.at_level("WARNING", logger="punt_lux.display.domain_pump"):
        pump.route_interaction(msg)
    assert caplog.records == []


def test_route_interaction_skips_message_without_scene_id(pump: DomainPump) -> None:
    """An InteractionMessage with no scene_id is dropped before Display.interact."""
    msg = InteractionMessage(element_id="b1", action="b1", value=True, scene_id=None)
    # No exception, no log assertions — wire-shape triage owns this case.
    pump.route_interaction(msg)


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
