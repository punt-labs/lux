"""Wire construction and value-shape validation for ``RowSelectionChanged``.

The table's selection event owns its ``from_wire``: the boundary check for its
payload shape (a set of row ids plus an explicit anchor) lives on the event
class, mirroring the container events.
"""

from __future__ import annotations

import pytest

from punt_lux.domain import ClientId, ElementId, SceneId
from punt_lux.domain.interaction_errors import WrongKindError
from punt_lux.domain.selection_interaction import RowSelectionChanged

_SCENE = SceneId("s1")
_ELEM = ElementId("e1")
_OWNER = ClientId("alice")


class TestRowSelectionChangedFromWire:
    def test_mapping_builds_the_set_and_anchor(self) -> None:
        event = RowSelectionChanged.from_wire(
            scene_id=_SCENE,
            element_id=_ELEM,
            owner_id=_OWNER,
            value={"row_ids": ["a", "c"], "anchor": "c"},
        )
        assert event.row_ids == ("a", "c")
        assert event.anchor == "c"
        assert event.kind == "row_selection_changed"

    def test_empty_selection_defaults_anchor_to_empty(self) -> None:
        event = RowSelectionChanged.from_wire(
            scene_id=_SCENE, element_id=_ELEM, owner_id=_OWNER, value={"row_ids": []}
        )
        assert event.row_ids == ()
        assert event.anchor == ""

    @pytest.mark.parametrize("value", [3, "a", None, ["a"]])
    def test_non_mapping_payload_is_rejected(self, value: object) -> None:
        with pytest.raises(WrongKindError):
            RowSelectionChanged.from_wire(
                scene_id=_SCENE, element_id=_ELEM, owner_id=_OWNER, value=value
            )

    @pytest.mark.parametrize("row_ids", [None, "a", [1, 2], ["a", 2]])
    def test_non_string_id_list_is_rejected(self, row_ids: object) -> None:
        with pytest.raises(WrongKindError):
            RowSelectionChanged.from_wire(
                scene_id=_SCENE,
                element_id=_ELEM,
                owner_id=_OWNER,
                value={"row_ids": row_ids, "anchor": ""},
            )

    @pytest.mark.parametrize("anchor", [3, ["a"], {"x": 1}])
    def test_non_string_anchor_is_rejected(self, anchor: object) -> None:
        with pytest.raises(WrongKindError):
            RowSelectionChanged.from_wire(
                scene_id=_SCENE,
                element_id=_ELEM,
                owner_id=_OWNER,
                value={"row_ids": ["a"], "anchor": anchor},
            )
