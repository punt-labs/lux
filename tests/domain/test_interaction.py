"""Verify ``ButtonClicked`` construction and immutability."""

from __future__ import annotations

import pytest

from punt_lux.domain import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked


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
