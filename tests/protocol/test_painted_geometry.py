"""``ElementGeometry`` / ``FrameGeometry`` wire roundtrips and decode errors."""

from __future__ import annotations

import pytest

from punt_lux.protocol.geometry import Rect
from punt_lux.protocol.painted_geometry import ElementGeometry, FrameGeometry

_RECT = Rect(x=10.0, y=20.0, width=300.0, height=150.0)


def test_element_geometry_roundtrips_through_wire_dict() -> None:
    geom = ElementGeometry(rect=_RECT, paint_sequence=3, stack_index=7)
    assert ElementGeometry.from_dict(geom.to_dict()) == geom


def test_frame_geometry_roundtrips_through_wire_dict() -> None:
    geom = FrameGeometry(rect=_RECT, stack_index=0)
    assert FrameGeometry.from_dict(geom.to_dict()) == geom


def test_element_to_dict_nests_the_rect_and_carries_z_order() -> None:
    geom = ElementGeometry(rect=_RECT, paint_sequence=1, stack_index=2)
    assert geom.to_dict() == {
        "rect": {"x": 10.0, "y": 20.0, "width": 300.0, "height": 150.0},
        "paint_sequence": 1,
        "stack_index": 2,
    }


@pytest.mark.parametrize("field", ["paint_sequence", "stack_index"])
def test_element_from_dict_rejects_a_missing_integer(field: str) -> None:
    full = ElementGeometry(rect=_RECT, paint_sequence=1, stack_index=2).to_dict()
    del full[field]
    with pytest.raises(ValueError, match=f"{field!r} must be an integer"):
        ElementGeometry.from_dict(full)


def test_from_dict_rejects_a_non_integer_stack_index() -> None:
    with pytest.raises(ValueError, match="stack_index"):
        FrameGeometry.from_dict({"rect": _RECT.to_dict(), "stack_index": 1.5})


def test_from_dict_rejects_bool_as_an_integer() -> None:
    # bool is an int subclass; a paint order or stack index is never True/False.
    with pytest.raises(ValueError, match="paint_sequence"):
        ElementGeometry.from_dict(
            {"rect": _RECT.to_dict(), "paint_sequence": True, "stack_index": 0}
        )


def test_from_dict_rejects_a_missing_rect() -> None:
    with pytest.raises(ValueError, match="'rect' must be a rect mapping"):
        FrameGeometry.from_dict({"stack_index": 0})


def test_from_dict_rejects_a_non_mapping_rect() -> None:
    with pytest.raises(ValueError, match="'rect' must be a rect mapping"):
        ElementGeometry.from_dict(
            {"rect": "nope", "paint_sequence": 0, "stack_index": 0}
        )
