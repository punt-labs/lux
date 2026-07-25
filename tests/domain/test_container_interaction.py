"""Wire construction and value-shape validation for the container events.

``TabChanged``, ``HeaderToggled``, and ``ModalClosed`` each own their
``from_wire`` — the boundary check for their payload shape lives on the event
class, so the kind knowledge is not re-encoded per element.
"""

from __future__ import annotations

import pytest

from punt_lux.domain import ClientId, ElementId, SceneId
from punt_lux.domain.container_interaction import (
    HeaderToggled,
    ModalClosed,
    TabChanged,
)
from punt_lux.domain.interaction_errors import WrongKindError

_SCENE = SceneId("s1")
_ELEM = ElementId("e1")
_OWNER = ClientId("alice")


class TestTabChangedFromWire:
    def test_str_builds_tab_changed(self) -> None:
        event = TabChanged.from_wire(
            scene_id=_SCENE, element_id=_ELEM, owner_id=_OWNER, value="second"
        )
        assert event.tab_id == "second"
        assert event.kind == "tab_changed"

    @pytest.mark.parametrize("value", [3, True, None, ["a"]])
    def test_non_str_is_rejected(self, value: object) -> None:
        with pytest.raises(WrongKindError):
            TabChanged.from_wire(
                scene_id=_SCENE, element_id=_ELEM, owner_id=_OWNER, value=value
            )


class TestHeaderToggledFromWire:
    @pytest.mark.parametrize("value", [True, False])
    def test_bool_builds_header_toggled(self, value: bool) -> None:
        event = HeaderToggled.from_wire(
            scene_id=_SCENE, element_id=_ELEM, owner_id=_OWNER, value=value
        )
        assert event.open is value
        assert event.kind == "header_toggled"

    @pytest.mark.parametrize("value", ["open", 1, None])
    def test_non_bool_is_rejected(self, value: object) -> None:
        with pytest.raises(WrongKindError):
            HeaderToggled.from_wire(
                scene_id=_SCENE, element_id=_ELEM, owner_id=_OWNER, value=value
            )


class TestModalClosedFromWire:
    def test_builds_ignoring_the_vestigial_value(self) -> None:
        # A dismissal has no payload; from_wire ignores the value it is given.
        event = ModalClosed.from_wire(
            scene_id=_SCENE, element_id=_ELEM, owner_id=_OWNER, value={"stray": 1}
        )
        assert event == ModalClosed(scene_id=_SCENE, element_id=_ELEM, owner_id=_OWNER)
