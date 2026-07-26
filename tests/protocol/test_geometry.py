"""``Rect`` wire-value roundtrips and decode-error behavior."""

from __future__ import annotations

import pytest

from punt_lux.protocol.geometry import Rect


def test_rect_roundtrips_through_wire_dict() -> None:
    rect = Rect(x=10.0, y=20.0, width=300.0, height=150.0)
    assert Rect.from_dict(rect.to_dict()) == rect


def test_to_dict_carries_all_four_fields() -> None:
    rect = Rect(x=1.5, y=2.5, width=3.5, height=4.5)
    assert rect.to_dict() == {"x": 1.5, "y": 2.5, "width": 3.5, "height": 4.5}


def test_from_dict_coerces_ints_to_float() -> None:
    rect = Rect.from_dict({"x": 0, "y": 0, "width": 20, "height": 8})
    assert rect == Rect(x=0.0, y=0.0, width=20.0, height=8.0)


@pytest.mark.parametrize("field", ["x", "y", "width", "height"])
def test_from_dict_rejects_a_missing_field(field: str) -> None:
    full = {"x": 1.0, "y": 2.0, "width": 3.0, "height": 4.0}
    del full[field]
    with pytest.raises(ValueError, match=f"Rect field {field!r} must be a number"):
        Rect.from_dict(full)


def test_from_dict_rejects_a_non_numeric_field() -> None:
    with pytest.raises(ValueError, match="width"):
        Rect.from_dict({"x": 1.0, "y": 2.0, "width": "wide", "height": 4.0})


def test_from_dict_rejects_bool_as_a_number() -> None:
    # bool is an int subclass; a painted coordinate is never True/False.
    with pytest.raises(ValueError, match="x"):
        Rect.from_dict({"x": True, "y": 2.0, "width": 3.0, "height": 4.0})


def test_rect_is_frozen() -> None:
    rect = Rect(x=0.0, y=0.0, width=1.0, height=1.0)
    with pytest.raises(AttributeError):
        rect.x = 5.0  # type: ignore[misc]
