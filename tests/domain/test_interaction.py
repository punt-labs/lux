"""Verify the Interaction sum type (PR 2)."""

from __future__ import annotations

import pytest

from punt_lux.domain import ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked


def test_button_clicked_serializes() -> None:
    interaction = ButtonClicked(scene_id=SceneId("s1"), element_id=ElementId("b1"))
    assert interaction.to_dict() == {
        "kind": "button_clicked",
        "scene_id": "s1",
        "element_id": "b1",
    }


def test_button_clicked_round_trips_through_wire() -> None:
    interaction = ButtonClicked(scene_id=SceneId("s1"), element_id=ElementId("b1"))
    restored = ButtonClicked.from_dict(interaction.to_dict())
    assert restored == interaction


def test_button_clicked_from_dict_rejects_missing_scene_id() -> None:
    with pytest.raises(ValueError, match=r"ButtonClicked.*scene_id"):
        ButtonClicked.from_dict({"kind": "button_clicked", "element_id": "b1"})


def test_button_clicked_from_dict_rejects_missing_element_id() -> None:
    with pytest.raises(ValueError, match=r"ButtonClicked.*element_id"):
        ButtonClicked.from_dict({"kind": "button_clicked", "scene_id": "s1"})
