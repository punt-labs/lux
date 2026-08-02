"""Tests for RemoteDispatchSpec — one interactive event an element declares."""

from __future__ import annotations

import dataclasses
from typing import ClassVar, Protocol, cast

import pytest

from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked, ValueChanged
from punt_lux.domain.interaction_errors import WrongKindError
from punt_lux.domain.remote_dispatch_spec import RemoteDispatchSpec
from punt_lux.domain.wire_event import WireEvent
from punt_lux.protocol.elements import (
    ButtonElement,
    CheckboxElement,
    CollapsingHeaderElement,
    ColorPickerElement,
    ComboElement,
    InputNumberElement,
    InputTextElement,
    ModalElement,
    RadioElement,
    SelectableElement,
    SliderElement,
    TabBarElement,
)

# One instance of every interactive ABC kind — the classes that declare a
# RemoteDispatchSpec. A new interactive kind adds itself here and nowhere else.
_INTERACTIVE_ELEMENTS = [
    ButtonElement(id="b", label="B"),
    CheckboxElement(id="c", label="C"),
    InputTextElement(id="it", label="IT"),
    InputNumberElement(id="in", label="IN"),
    SliderElement(id="s", label="S"),
    ColorPickerElement(id="cp", label="CP"),
    ComboElement(id="co", label="CO", items=["a", "b"]),
    RadioElement(id="r", label="R", items=["a", "b"]),
    SelectableElement(id="se", label="SE"),
    CollapsingHeaderElement(id="ch", label="CH"),
    TabBarElement(id="tb"),
    ModalElement(id="m", title="M"),
]


class _Kinded(Protocol):
    """Read-only view of a concrete event's wire ``kind`` tag."""

    kind: ClassVar[str]


class TestRemoteDispatchSpec:
    def test_construction_and_field_access(self) -> None:
        spec = RemoteDispatchSpec(ButtonClicked, "confirm", "button_clicked")
        assert spec.event_type is ButtonClicked
        assert spec.action == "confirm"
        assert spec.event_kind == "button_clicked"

    def test_action_may_be_none(self) -> None:
        # None is the documented "fall back to the element id" sentinel the
        # wrap loop applies when a button carries no explicit action.
        spec = RemoteDispatchSpec(ButtonClicked, None, "button_clicked")
        assert spec.action is None

    def test_frozen_rejects_mutation(self) -> None:
        spec = RemoteDispatchSpec(ValueChanged, "changed", "value_changed")
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.action = "other"  # type: ignore[misc]  # frozen dataclass

    def test_equality_by_value(self) -> None:
        a = RemoteDispatchSpec(ButtonClicked, "confirm", "button_clicked")
        b = RemoteDispatchSpec(ButtonClicked, "confirm", "button_clicked")
        c = RemoteDispatchSpec(ValueChanged, "changed", "value_changed")
        assert a == b
        assert a != c


class TestBuildEvent:
    def test_delegates_to_the_event_types_from_wire(self) -> None:
        spec = RemoteDispatchSpec(ValueChanged, "changed", "value_changed")
        event = spec.build_event(
            scene_id=SceneId("s"),
            element_id=ElementId("e"),
            owner_id=ClientId("o"),
            value=True,
        )
        assert isinstance(event, ValueChanged)
        assert event.value is True

    def test_propagates_wrong_kind_from_shape_validation(self) -> None:
        spec = RemoteDispatchSpec(ValueChanged, "changed", "value_changed")
        with pytest.raises(WrongKindError):
            spec.build_event(
                scene_id=SceneId("s"),
                element_id=ElementId("e"),
                owner_id=ClientId("o"),
                value=[1, 2],  # non-scalar
            )


class TestSingleRegistrationPoint:
    """Each interactive element's spec fully and consistently declares its kind.

    The spec IS the single place a new interactive kind registers: its wire tag
    (``event_kind``) must match the event class's own ``kind``, and that event
    class must be a ``WireEvent`` (it owns ``from_wire``). A new kind that
    mismatches the tag, or names an event with no ``from_wire``, fails here.
    """

    def test_every_interactive_element_declares_at_least_one_spec(self) -> None:
        for elem in _INTERACTIVE_ELEMENTS:
            assert elem._remote_dispatch_specs(), (
                f"{type(elem).__name__} declares no RemoteDispatchSpec"
            )

    def test_spec_wire_tag_matches_its_event_class_kind(self) -> None:
        for elem in _INTERACTIVE_ELEMENTS:
            for spec in elem._remote_dispatch_specs():
                # Each concrete event carries its own ``kind`` ClassVar; the
                # spec's wire tag must match it. ``kind`` is intentionally off
                # the WireEvent protocol (see event_protocol), so read it through
                # a narrow local protocol.
                kinded = cast("type[_Kinded]", spec.event_type)
                assert spec.event_kind == kinded.kind

    def test_every_spec_event_type_is_wire_constructible(self) -> None:
        for elem in _INTERACTIVE_ELEMENTS:
            for spec in elem._remote_dispatch_specs():
                assert hasattr(spec.event_type, "from_wire")
                # An instance the spec builds satisfies the WireEvent protocol.
                event = spec.build_event(
                    scene_id=SceneId("s"),
                    element_id=ElementId(elem.id),
                    owner_id=ClientId("o"),
                    value=_sample_value(spec.event_kind),
                )
                assert isinstance(event, WireEvent)

    def test_every_spec_event_publishes_a_payload_naming_its_element(self) -> None:
        # A publish-decorated handler sends what the event renders, so a new
        # interactive kind whose event forgets ``to_payload`` publishes nothing
        # a subscriber can act on. This is where that is caught.
        for elem in _INTERACTIVE_ELEMENTS:
            for spec in elem._remote_dispatch_specs():
                event = spec.build_event(
                    scene_id=SceneId("s"),
                    element_id=ElementId(elem.id),
                    owner_id=ClientId("o"),
                    value=_sample_value(spec.event_kind),
                )
                payload = event.to_payload()
                assert payload["kind"] == spec.event_kind
                assert payload["scene_id"] == "s"
                assert payload["element_id"] == elem.id


def _sample_value(event_kind: str) -> object:
    """Return a shape-valid sample payload for ``event_kind``."""
    return {
        "value_changed": 1,
        "header_toggled": True,
        "tab_changed": "tab",
        "button_clicked": True,
        "modal_closed": None,
    }[event_kind]
