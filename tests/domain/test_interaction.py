"""Verify ``ButtonClicked`` / ``ValueChanged`` construction and wire building."""

from __future__ import annotations

import pytest

from punt_lux.domain import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked, ValueChanged
from punt_lux.domain.interaction_errors import WrongKindError

_SCENE = SceneId("s1")
_ELEM = ElementId("e1")
_OWNER = ClientId("alice")


def test_button_clicked_constructible() -> None:
    """ButtonClicked can be constructed directly with its three fields."""
    event = ButtonClicked(
        scene_id=SceneId("s1"),
        element_id=ElementId("b1"),
        owner_id=ClientId("alice"),
    )
    assert event.scene_id == SceneId("s1")
    assert event.element_id == ElementId("b1")
    assert event.owner_id == ClientId("alice")
    assert event.kind == "button_clicked"


def test_button_clicked_is_frozen() -> None:
    """Field writes after construction raise ``FrozenInstanceError``."""
    event = ButtonClicked(
        scene_id=SceneId("s1"),
        element_id=ElementId("b1"),
        owner_id=ClientId("alice"),
    )
    with pytest.raises(AttributeError):
        # frozen dataclass forbids attribute mutation; mypy can't see
        # through to the synthesized __setattr__.
        event.element_id = ElementId("b2")  # type: ignore[misc]


class TestButtonClickedFromWire:
    def test_builds_ignoring_the_vestigial_value(self) -> None:
        # A click has no payload; from_wire ignores whatever value it is given.
        event = ButtonClicked.from_wire(
            scene_id=_SCENE, element_id=_ELEM, owner_id=_OWNER, value="anything"
        )
        assert event == ButtonClicked(
            scene_id=_SCENE, element_id=_ELEM, owner_id=_OWNER
        )


class TestValueChangedFromWire:
    @pytest.mark.parametrize("value", [True, 3, 2.5, "hi"])
    def test_accepts_any_scalar(self, value: bool | int | float | str) -> None:
        event = ValueChanged.from_wire(
            scene_id=_SCENE, element_id=_ELEM, owner_id=_OWNER, value=value
        )
        assert event.value == value

    @pytest.mark.parametrize("value", [[1, 2], {"a": 1}, None, (1,)])
    def test_rejects_a_non_scalar(self, value: object) -> None:
        # The boundary check is the shared value-input shape (a scalar); the
        # precise per-kind shape is the firing element's DES-039 invariant.
        with pytest.raises(WrongKindError):
            ValueChanged.from_wire(
                scene_id=_SCENE, element_id=_ELEM, owner_id=_OWNER, value=value
            )
