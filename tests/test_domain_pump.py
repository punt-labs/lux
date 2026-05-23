"""Tests for ``DomainPump`` — the native-kind dual-write route.

Focused on the routing predicate.  Display.apply itself is covered by
``tests/domain/test_display.py``; here we verify what the pump decides
to forward.

PR 2 widened the route from "basics-only" to "basics + inputs".  Any
remaining non-native kind (group, window, draw, table, plot, …) still
disqualifies a scene from the new path until subsequent PRs migrate
those families.
"""

from __future__ import annotations

import pytest

from punt_lux.display.domain_pump import DomainPump
from punt_lux.domain.display import Display
from punt_lux.domain.event import ButtonPressed, Event
from punt_lux.domain.ids import ElementId, SceneId
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
    """PR 2: inputs kinds are native — flow through the pump unchanged."""
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


def test_route_interaction_emits_button_pressed_for_button_click(
    pump: DomainPump,
) -> None:
    """Production-caller test: route_interaction lifts a wire click into ButtonPressed.

    PY-RF-2: ButtonClicked + ButtonPressed both gain a production caller here
    (DomainPump) and a test caller (this test).  Without route_interaction the
    new domain types are dead code; without this test the pump's translation
    is untested.
    """
    # Seed the domain Display with a Button by routing a scene through.
    scene = SceneMessage(id="s1", elements=[ButtonElement(id="b1", label="OK")])
    pump.route(scene)

    observed: list[Event] = []
    pump._display.subscribe(observed.append)

    msg = InteractionMessage(
        element_id="b1",
        action="b1",
        ts=1.0,
        value=True,
        scene_id="s1",
    )
    pump.route_interaction(msg)

    assert len(observed) == 1
    event = observed[0]
    assert isinstance(event, ButtonPressed)
    assert event.element_id == ElementId("b1")


def test_route_interaction_skips_non_button_kinds(pump: DomainPump) -> None:
    """Slider/Checkbox/etc. interactions are not yet domain-routed."""
    scene = SceneMessage(id="s1", elements=[SliderElement(id="sl1", label="Vol")])
    pump.route(scene)

    observed: list[Event] = []
    pump._display.subscribe(observed.append)

    msg = InteractionMessage(
        element_id="sl1",
        action="changed",
        ts=1.0,
        value=42.0,
        scene_id="s1",
    )
    pump.route_interaction(msg)

    assert observed == []


def test_route_interaction_silently_skips_unknown_scene(pump: DomainPump) -> None:
    """A click on a scene the domain Display doesn't know is silently ignored.

    Mixed-scene case: the wire saw a scene SceneManager renders, but the
    pump's earlier ``route`` skipped it.  The click reaches _emit_event but
    the pump has no way to translate it — drop it without warning.
    """
    observed: list[Event] = []
    pump._display.subscribe(observed.append)

    msg = InteractionMessage(
        element_id="b1",
        action="b1",
        ts=1.0,
        value=True,
        scene_id="never-seen",
    )
    pump.route_interaction(msg)
    assert observed == []


def test_route_interaction_warns_on_unknown_element_in_known_scene(
    pump: DomainPump, caplog: pytest.LogCaptureFixture
) -> None:
    """SFH M1: unknown element in a tracked scene is a divergence signal.

    Wire saw an element the domain forgot, OR renderer fired against a
    stale id.  Either case is exactly what the parallel Display is meant
    to detect; suppressing the warning loses that signal.
    """
    scene = SceneMessage(id="s1", elements=[ButtonElement(id="b1", label="OK")])
    pump.route(scene)

    observed: list[Event] = []
    pump._display.subscribe(observed.append)

    msg = InteractionMessage(
        element_id="ghost",
        action="ghost",
        ts=1.0,
        value=True,
        scene_id="s1",
    )
    with caplog.at_level("WARNING", logger="punt_lux.display.domain_pump"):
        pump.route_interaction(msg)
    assert observed == []
    messages = [r.getMessage() for r in caplog.records]
    assert any("unknown element" in m and "ghost" in m for m in messages), (
        f"expected unknown-element warning; got {messages}"
    )


def test_route_interaction_warns_on_non_true_button_value_and_does_not_route(
    pump: DomainPump, caplog: pytest.LogCaptureFixture
) -> None:
    """Bugbot HIGH (PR #187): a button-element message whose value is not
    boolean True (e.g. a dict from a colliding menu emit) MUST NOT route
    as a ButtonPressed.  The warning surfaces the renderer bug.
    """
    scene = SceneMessage(id="s1", elements=[ButtonElement(id="b1", label="OK")])
    pump.route(scene)

    observed: list[Event] = []
    pump._display.subscribe(observed.append)

    msg = InteractionMessage(
        element_id="b1",
        action="b1",
        ts=1.0,
        value=False,  # phantom click — renderer bug
        scene_id="s1",
    )
    with caplog.at_level("WARNING", logger="punt_lux.display.domain_pump"):
        pump.route_interaction(msg)
    # NOT routed — strict value-shape check protects against spurious events.
    assert observed == []
    messages = [r.getMessage() for r in caplog.records]
    assert any("not True (boolean)" in m for m in messages), (
        f"expected boolean-True warning; got {messages}"
    )


def test_route_interaction_skips_menu_action_without_warning(
    pump: DomainPump, caplog: pytest.LogCaptureFixture
) -> None:
    """Bugbot MED (PR #187): menu emissions have action="menu" and ids that
    are not scene elements.  They MUST NOT trip the unknown-element
    divergence warning — that warning exists for real divergence.
    """
    scene = SceneMessage(id="s1", elements=[ButtonElement(id="b1", label="OK")])
    pump.route(scene)

    observed: list[Event] = []
    pump._display.subscribe(observed.append)

    menu_msg = InteractionMessage(
        element_id="menu.file.open",
        action="menu",
        ts=1.0,
        value={"menu": "File", "item": "Open"},
        scene_id="s1",
    )
    with caplog.at_level("WARNING", logger="punt_lux.display.domain_pump"):
        pump.route_interaction(menu_msg)
    assert observed == []
    assert caplog.records == [], (
        f"menu action must not log; got {[r.getMessage() for r in caplog.records]}"
    )


def test_route_interaction_skips_frame_close_action_without_warning(
    pump: DomainPump, caplog: pytest.LogCaptureFixture
) -> None:
    """Frame-close events are display-chrome, not element-targeted."""
    scene = SceneMessage(id="s1", elements=[ButtonElement(id="b1", label="OK")])
    pump.route(scene)

    observed: list[Event] = []
    pump._display.subscribe(observed.append)

    msg = InteractionMessage(
        element_id="frame-1",
        action="frame_close",
        ts=1.0,
        scene_id="s1",
    )
    with caplog.at_level("WARNING", logger="punt_lux.display.domain_pump"):
        pump.route_interaction(msg)
    assert observed == []
    assert caplog.records == []


def test_route_interaction_menu_id_colliding_with_button_does_not_fire(
    pump: DomainPump, caplog: pytest.LogCaptureFixture
) -> None:
    """Bugbot HIGH (PR #187): defense-in-depth — even if the menu filter
    were bypassed, a menu emission whose id collides with a real button
    in the scene MUST NOT fire ButtonPressed.  Verified via the strict
    ``value is True`` check in ``_is_button_click``.
    """
    scene = SceneMessage(id="s1", elements=[ButtonElement(id="b1", label="OK")])
    pump.route(scene)

    observed: list[Event] = []
    pump._display.subscribe(observed.append)

    # action != "menu" so the early skip doesn't fire — simulates a hypothetical
    # routing oversight to confirm the value-shape check still protects.
    msg = InteractionMessage(
        element_id="b1",  # collides with the button id
        action="something_else",
        ts=1.0,
        value={"menu": "File", "item": "Open"},  # dict, not bool True
        scene_id="s1",
    )
    with caplog.at_level("WARNING", logger="punt_lux.display.domain_pump"):
        pump.route_interaction(msg)
    assert observed == []  # phantom ButtonPressed suppressed
    messages = [r.getMessage() for r in caplog.records]
    assert any("not True (boolean)" in m for m in messages)


def test_route_interaction_skips_message_without_scene_id(pump: DomainPump) -> None:
    observed: list[Event] = []
    pump._display.subscribe(observed.append)

    msg = InteractionMessage(
        element_id="b1",
        action="b1",
        ts=1.0,
        value=True,
        scene_id=None,
    )
    pump.route_interaction(msg)
    assert observed == []


def test_route_multiple_anonymous_separators(
    pump: DomainPump, caplog: pytest.LogCaptureFixture
) -> None:
    """Copilot CP-NEW-1: anonymous SeparatorElements must not collide.

    Separators rarely receive explicit ids — the common case is
    ``SeparatorElement()`` with ``id=""``.  Without per-element id
    synthesis the second and third anonymous separators would hit the
    Display's ``DuplicateIdError`` guard, the pump would only log a
    warning, and SceneManager (which has no uniqueness check) would
    keep all three.  The two stores would diverge.

    The pump synthesizes ``<kind>:<index>`` ids inside the domain
    boundary so every anonymous element occupies a distinct slot in the
    snapshot.  The wire and renderer continue to see the original
    empty id — synthesis is local to the dual-write path.
    """
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
