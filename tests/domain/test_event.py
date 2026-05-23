"""Verify Event sum types (success events + typed errors)."""

from __future__ import annotations

from punt_lux.domain import ClientId, ElementId, SceneId
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
)
from punt_lux.domain.ownership import OwnershipError


def test_element_added_serializes_with_optional_parent() -> None:
    ev = ElementAdded(
        scene_id=SceneId("s1"),
        element_id=ElementId("e1"),
        owner_id=ClientId("alice"),
        parent_id=None,
    )
    payload = ev.to_dict()
    assert payload["kind"] == "element_added"
    assert "parent_id" not in payload
    ev2 = ElementAdded(
        scene_id=SceneId("s1"),
        element_id=ElementId("e1"),
        owner_id=ClientId("alice"),
        parent_id=ElementId("g1"),
    )
    assert ev2.to_dict()["parent_id"] == "g1"


def test_element_removed_carries_owner() -> None:
    ev = ElementRemoved(
        scene_id=SceneId("s1"),
        element_id=ElementId("e1"),
        owner_id=ClientId("alice"),
    )
    assert ev.to_dict()["owner_id"] == "alice"


def test_element_updated_carries_old_and_new_values() -> None:
    ev = ElementUpdated(
        scene_id=SceneId("s1"),
        element_id=ElementId("e1"),
        owner_id=ClientId("alice"),
        field="content",
        old_value="before",
        new_value="after",
    )
    payload = ev.to_dict()
    assert payload["old_value"] == "before"
    assert payload["new_value"] == "after"


def test_button_pressed_serializes() -> None:
    ev = ButtonPressed(
        scene_id=SceneId("s1"),
        element_id=ElementId("b1"),
        owner_id=ClientId("alice"),
    )
    assert ev.to_dict() == {
        "kind": "button_pressed",
        "scene_id": "s1",
        "element_id": "b1",
        "owner_id": "alice",
    }


def test_ownership_error_distinguishes_attempter_and_owner() -> None:
    err = OwnershipError(
        scene_id=SceneId("s1"),
        element_id=ElementId("e1"),
        attempting_client_id=ClientId("bob"),
        owning_client_id=ClientId("alice"),
    )
    payload = err.to_dict()
    assert payload["attempting_client_id"] == "bob"
    assert payload["owning_client_id"] == "alice"


def test_duplicate_id_error_payload() -> None:
    err = DuplicateIdError(scene_id=SceneId("s1"), element_id=ElementId("e1"))
    assert err.to_dict() == {
        "kind": "duplicate_id_error",
        "scene_id": "s1",
        "element_id": "e1",
    }


def test_property_type_error_records_expected_and_got() -> None:
    err = PropertyTypeError(
        scene_id=SceneId("s1"),
        element_id=ElementId("e1"),
        field="fraction",
        expected_type="float",
        got_value="oops",
    )
    payload = err.to_dict()
    assert payload["expected_type"] == "float"
    assert payload["got_value"] == "oops"


def test_unknown_element_error_payload() -> None:
    err = UnknownElementError(scene_id=SceneId("s1"), element_id=ElementId("ghost"))
    assert err.to_dict()["element_id"] == "ghost"
