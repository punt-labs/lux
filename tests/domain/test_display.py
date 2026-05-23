"""Display single-runtime tests — the acceptance template from domain-model.md.

No ImGui. No socket. No JSON. A real test of real invariants against
real domain objects. Covers every Update kind, every Event/Error
branch, and pub/sub.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self

from punt_lux.domain import ElementId, SceneId
from punt_lux.domain.display import Display
from punt_lux.domain.error import (
    DuplicateIdError,
    PropertyTypeError,
    UnknownElementError,
)
from punt_lux.domain.event import (
    ButtonPressed,
    ElementAdded,
    ElementRemoved,
    ElementUpdated,
    Event,
)
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.domain.ownership import OwnershipError
from punt_lux.domain.snapshot import SceneSnapshot
from punt_lux.domain.update import AddElement, RemoveElement, SetProperty


def _button(snap: SceneSnapshot, eid: ElementId) -> _Button:
    """Narrow ``snap.element(eid)`` to the concrete _Button used by these tests."""
    elem = snap.element(eid)
    assert isinstance(elem, _Button)
    return elem


@dataclass(frozen=True, slots=True)
class _Button:
    """Stand-in for the future ButtonElement — exercises Display end-to-end."""

    id: ElementId
    label: str
    disabled: bool = False
    kind: Literal["button"] = "button"
    tooltip: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "kind": self.kind,
            "label": self.label,
            "disabled": self.disabled,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(
            id=ElementId(str(d["id"])),
            label=str(d.get("label", "")),
            disabled=bool(d.get("disabled", False)),
        )


@dataclass(frozen=True, slots=True)
class _Progress:
    """Stand-in for ProgressElement — exercises the float-field type check."""

    id: ElementId
    fraction: float = 0.0
    count: int = 0
    kind: Literal["progress"] = "progress"
    tooltip: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "kind": self.kind,
            "fraction": self.fraction,
            "count": self.count,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        raw_fraction = d.get("fraction", 0.0)
        raw_count = d.get("count", 0)
        assert isinstance(raw_fraction, int | float)
        assert isinstance(raw_count, int) and not isinstance(raw_count, bool)
        return cls(
            id=ElementId(str(d["id"])),
            fraction=float(raw_fraction),
            count=raw_count,
        )


def _progress(snap: SceneSnapshot, eid: ElementId) -> _Progress:
    """Narrow ``snap.element(eid)`` to the concrete _Progress used by these tests."""
    elem = snap.element(eid)
    assert isinstance(elem, _Progress)
    return elem


# -- topology ---------------------------------------------------------------


def test_connect_assigns_unique_client_ids() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    bob = display.connect_client(name="bob")
    assert alice != bob
    assert {alice, bob} == set(display.client_ids())


def test_add_scene_is_idempotent() -> None:
    display = Display()
    display.add_scene(SceneId("s1"))
    display.add_scene(SceneId("s1"))
    assert display.scene_ids() == frozenset({SceneId("s1")})


# -- AddElement -------------------------------------------------------------


def test_add_element_emits_element_added() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))
    btn = _Button(id=ElementId("b1"), label="hi")
    result = display.apply(alice, AddElement(scene_id=SceneId("s1"), element=btn))
    assert isinstance(result, ElementAdded)
    assert result.element_id == ElementId("b1")
    assert result.owner_id == alice
    assert display.snapshot(SceneId("s1")).element(ElementId("b1")) is btn


def test_add_element_duplicate_id_is_refused() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))
    btn = _Button(id=ElementId("b1"), label="hi")
    display.apply(alice, AddElement(scene_id=SceneId("s1"), element=btn))
    duplicate = display.apply(alice, AddElement(scene_id=SceneId("s1"), element=btn))
    assert isinstance(duplicate, DuplicateIdError)
    # State is unchanged: the original element is still there.
    assert _button(display.snapshot(SceneId("s1")), ElementId("b1")).label == "hi"


def test_add_element_to_unknown_scene_returns_unknown_element() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    btn = _Button(id=ElementId("b1"), label="hi")
    result = display.apply(alice, AddElement(scene_id=SceneId("ghost"), element=btn))
    assert isinstance(result, UnknownElementError)


# -- RemoveElement ----------------------------------------------------------


def test_remove_element_emits_element_removed() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="hi"),
        ),
    )
    result = display.apply(
        alice, RemoveElement(scene_id=SceneId("s1"), element_id=ElementId("b1"))
    )
    assert isinstance(result, ElementRemoved)
    assert not display.snapshot(SceneId("s1")).has(ElementId("b1"))


def test_remove_unknown_element_returns_unknown_element() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))
    result = display.apply(
        alice, RemoveElement(scene_id=SceneId("s1"), element_id=ElementId("ghost"))
    )
    assert isinstance(result, UnknownElementError)


# -- SetProperty ------------------------------------------------------------


def test_set_property_emits_element_updated() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="hi"),
        ),
    )
    result = display.apply(
        alice,
        SetProperty(
            scene_id=SceneId("s1"),
            element_id=ElementId("b1"),
            field="label",
            value="hello",
        ),
    )
    assert isinstance(result, ElementUpdated)
    assert result.old_value == "hi"
    assert result.new_value == "hello"
    snap = display.snapshot(SceneId("s1"))
    assert _button(snap, ElementId("b1")).label == "hello"


def test_set_property_with_wrong_type_returns_property_type_error() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="hi"),
        ),
    )
    result = display.apply(
        alice,
        SetProperty(
            scene_id=SceneId("s1"),
            element_id=ElementId("b1"),
            field="label",
            value=42,  # int into a str field
        ),
    )
    assert isinstance(result, PropertyTypeError)
    # State unchanged.
    assert _button(display.snapshot(SceneId("s1")), ElementId("b1")).label == "hi"


def test_set_property_on_unknown_field_returns_property_type_error() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="hi"),
        ),
    )
    result = display.apply(
        alice,
        SetProperty(
            scene_id=SceneId("s1"),
            element_id=ElementId("b1"),
            field="not_a_field",
            value="x",
        ),
    )
    assert isinstance(result, PropertyTypeError)


def test_set_property_on_bool_field_accepts_bool() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="hi"),
        ),
    )
    result = display.apply(
        alice,
        SetProperty(
            scene_id=SceneId("s1"),
            element_id=ElementId("b1"),
            field="disabled",
            value=True,
        ),
    )
    assert isinstance(result, ElementUpdated)


def test_set_property_on_float_field_accepts_int() -> None:
    """Copilot CP-NEW5: JSON int literals must satisfy float-annotated fields.

    ``json.loads('{"fraction": 1}')`` yields ``int`` 1, not ``float`` 1.0.  The
    wire-boundary ``WireContext.require_number`` coerces both; ``Display._apply_set``
    must match that semantics or a legitimate integer fraction is wrongly refused.
    """
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Progress(id=ElementId("p1")),
        ),
    )
    result = display.apply(
        alice,
        SetProperty(
            scene_id=SceneId("s1"),
            element_id=ElementId("p1"),
            field="fraction",
            value=1,  # integer literal — must satisfy fraction: float
        ),
    )
    assert isinstance(result, ElementUpdated)
    assert result.new_value == 1
    assert _progress(display.snapshot(SceneId("s1")), ElementId("p1")).fraction == 1


def test_set_property_on_int_field_refuses_float() -> None:
    """The inverse asymmetry: float values do NOT satisfy an ``int`` annotation.

    ``json.dumps(1.0)`` is ``"1.0"``, distinct from ``json.dumps(1)`` (``"1"``),
    so a float literal arriving for an int-only field is a real type mismatch.
    """
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Progress(id=ElementId("p1")),
        ),
    )
    result = display.apply(
        alice,
        SetProperty(
            scene_id=SceneId("s1"),
            element_id=ElementId("p1"),
            field="count",
            value=1.0,  # float literal into an int field — refused
        ),
    )
    assert isinstance(result, PropertyTypeError)


def test_set_property_on_float_field_still_refuses_bool() -> None:
    """``bool`` is a subclass of ``int`` but must not silently coerce to ``float``."""
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Progress(id=ElementId("p1")),
        ),
    )
    result = display.apply(
        alice,
        SetProperty(
            scene_id=SceneId("s1"),
            element_id=ElementId("p1"),
            field="fraction",
            value=True,
        ),
    )
    assert isinstance(result, PropertyTypeError)


# -- Ownership (the domain-model.md template scenario) ----------------------


def test_cross_client_set_property_is_refused() -> None:
    """Acceptance template from docs/architecture/domain-model.md §Testability."""
    display = Display()
    alice = display.connect_client(name="alice")
    bob = display.connect_client(name="bob")
    display.add_scene(SceneId("s1"))

    added = display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="hi"),
        ),
    )
    assert isinstance(added, ElementAdded)

    refused = display.apply(
        bob,
        SetProperty(
            scene_id=SceneId("s1"),
            element_id=ElementId("b1"),
            field="label",
            value="evil",
        ),
    )
    assert isinstance(refused, OwnershipError)
    assert refused.attempting_client_id == bob
    assert refused.owning_client_id == alice

    # State unchanged: validation ran BEFORE mutation per PY-EH-1.
    assert _button(display.snapshot(SceneId("s1")), ElementId("b1")).label == "hi"


def test_cross_client_remove_is_refused() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    bob = display.connect_client(name="bob")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="hi"),
        ),
    )
    refused = display.apply(
        bob, RemoveElement(scene_id=SceneId("s1"), element_id=ElementId("b1"))
    )
    assert isinstance(refused, OwnershipError)
    assert display.snapshot(SceneId("s1")).has(ElementId("b1"))


def test_unknown_client_returns_ownership_error() -> None:
    display = Display()
    display.add_scene(SceneId("s1"))
    from punt_lux.domain.ids import ClientId

    ghost = ClientId("ghost")
    refused = display.apply(
        ghost,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="hi"),
        ),
    )
    assert isinstance(refused, OwnershipError)


# -- Disconnect cascade -----------------------------------------------------


def test_disconnect_cascade_removes_owned_elements_and_emits_removed() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="hi"),
        ),
    )
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b2"), label="bye"),
        ),
    )
    events = display.disconnect_client(alice)
    assert len(events) == 2
    assert {e.element_id for e in events} == {ElementId("b1"), ElementId("b2")}
    assert alice not in display.client_ids()
    assert display.snapshot(SceneId("s1")).element_ids == frozenset()


def test_disconnect_unknown_client_is_noop() -> None:
    display = Display()
    from punt_lux.domain.ids import ClientId

    events = display.disconnect_client(ClientId("ghost"))
    assert events == ()


# -- Pub/sub ----------------------------------------------------------------


def test_subscribe_receives_success_events() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))

    received: list[Event] = []
    sub = display.subscribe(received.append)

    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="hi"),
        ),
    )
    assert len(received) == 1
    assert isinstance(received[0], ElementAdded)

    sub.cancel()
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b2"), label="bye"),
        ),
    )
    assert len(received) == 1  # cancelled subscriber did not receive the second event


def test_subscribe_does_not_receive_errors() -> None:
    """Failure responses are returned to the caller, not emitted to subscribers."""
    display = Display()
    alice = display.connect_client(name="alice")
    bob = display.connect_client(name="bob")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="hi"),
        ),
    )

    received: list[Event] = []
    display.subscribe(received.append)
    display.apply(
        bob,
        SetProperty(
            scene_id=SceneId("s1"),
            element_id=ElementId("b1"),
            field="label",
            value="evil",
        ),
    )
    assert received == []


# -- Snapshot ---------------------------------------------------------------


def test_snapshot_is_a_point_in_time_view() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="hi"),
        ),
    )
    before = display.snapshot(SceneId("s1"))
    display.apply(
        alice,
        SetProperty(
            scene_id=SceneId("s1"),
            element_id=ElementId("b1"),
            field="label",
            value="hello",
        ),
    )
    # The earlier snapshot is decoupled from the live state.
    assert _button(before, ElementId("b1")).label == "hi"
    assert _button(display.snapshot(SceneId("s1")), ElementId("b1")).label == "hello"


# -- Display.interact ------------------------------------------------------


def test_interact_button_emits_button_pressed_to_subscriber() -> None:
    """Acceptance: a click on a Button reaches every subscriber as ButtonPressed."""
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="OK"),
        ),
    )
    observed: list[Event] = []
    display.subscribe(observed.append)

    result = display.interact(
        alice, ButtonClicked(scene_id=SceneId("s1"), element_id=ElementId("b1"))
    )

    assert isinstance(result, ButtonPressed)
    assert result.owner_id == alice
    assert result.element_id == ElementId("b1")
    assert [type(ev) for ev in observed] == [ButtonPressed]


def test_interact_returns_unknown_element_error_for_missing_element() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))
    # Note: no AddElement — element_id "ghost" doesn't exist.

    result = display.interact(
        alice, ButtonClicked(scene_id=SceneId("s1"), element_id=ElementId("ghost"))
    )
    assert isinstance(result, UnknownElementError)


def test_interact_returns_unknown_element_error_for_missing_scene() -> None:
    display = Display()
    alice = display.connect_client(name="alice")

    result = display.interact(
        alice, ButtonClicked(scene_id=SceneId("no-such"), element_id=ElementId("b1"))
    )
    assert isinstance(result, UnknownElementError)


def test_interact_returns_ownership_error_for_unknown_client() -> None:
    from punt_lux.domain import ClientId

    display = Display()
    display.add_scene(SceneId("s1"))
    result = display.interact(
        ClientId("not-registered"),
        ButtonClicked(scene_id=SceneId("s1"), element_id=ElementId("b1")),
    )
    assert isinstance(result, OwnershipError)


def test_interact_returns_ownership_error_when_client_does_not_own_element() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    bob = display.connect_client(name="bob")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="OK"),
        ),
    )

    result = display.interact(
        bob, ButtonClicked(scene_id=SceneId("s1"), element_id=ElementId("b1"))
    )
    assert isinstance(result, OwnershipError)
    assert result.attempting_client_id == bob
    assert result.owning_client_id == alice


def test_interact_validation_precedes_mutation() -> None:
    """PY-EH-1: unauthorized click leaves snapshot unchanged.

    A failing ``interact`` returns an Error and the element state in the
    snapshot is identical before and after — interact never mutates.
    """
    display = Display()
    alice = display.connect_client(name="alice")
    bob = display.connect_client(name="bob")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="OK"),
        ),
    )
    before = display.snapshot(SceneId("s1"))

    result = display.interact(
        bob, ButtonClicked(scene_id=SceneId("s1"), element_id=ElementId("b1"))
    )
    assert isinstance(result, OwnershipError)
    after = display.snapshot(SceneId("s1"))
    assert _button(before, ElementId("b1")) == _button(after, ElementId("b1"))


def test_interact_does_not_emit_event_on_failure() -> None:
    display = Display()
    alice = display.connect_client(name="alice")
    bob = display.connect_client(name="bob")
    display.add_scene(SceneId("s1"))
    display.apply(
        alice,
        AddElement(
            scene_id=SceneId("s1"),
            element=_Button(id=ElementId("b1"), label="OK"),
        ),
    )
    observed: list[Event] = []
    display.subscribe(observed.append)

    # ownership failure — no event should fire
    display.interact(
        bob, ButtonClicked(scene_id=SceneId("s1"), element_id=ElementId("b1"))
    )
    assert observed == []
