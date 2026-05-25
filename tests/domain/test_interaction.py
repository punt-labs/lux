"""Verify the ``ButtonClicked`` factory-token guard."""

from __future__ import annotations

import pytest

from punt_lux.domain import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import BUTTON_CLICKED_TOKEN, ButtonClicked


def test_button_clicked_constructible_with_factory_token() -> None:
    """The token gate accepts the canonical sentinel."""
    event = ButtonClicked(
        scene_id=SceneId("s1"),
        element_id=ElementId("b1"),
        owner_id=ClientId("alice"),
        _token=BUTTON_CLICKED_TOKEN,
    )
    assert event.scene_id == SceneId("s1")
    assert event.element_id == ElementId("b1")
    assert event.owner_id == ClientId("alice")
    assert event.kind == "button_clicked"


def test_button_clicked_rejects_construction_without_token() -> None:
    """Any sentinel other than the canonical token is refused."""
    with pytest.raises(TypeError, match=r"Display\.interact"):
        ButtonClicked(
            scene_id=SceneId("s1"),
            element_id=ElementId("b1"),
            owner_id=ClientId("alice"),
            _token=object(),
        )


def test_button_clicked_is_frozen() -> None:
    """Field writes after construction raise ``FrozenInstanceError``."""
    event = ButtonClicked(
        scene_id=SceneId("s1"),
        element_id=ElementId("b1"),
        owner_id=ClientId("alice"),
        _token=BUTTON_CLICKED_TOKEN,
    )
    with pytest.raises(AttributeError):
        # frozen dataclass forbids attribute mutation; mypy can't see
        # through to the synthesized __setattr__.
        event.element_id = ElementId("b2")  # type: ignore[misc]
