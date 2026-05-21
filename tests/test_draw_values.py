"""Tests for draw-command value primitives and ``WireContext``."""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.draw_values import Color, Point2, Thickness
from punt_lux.protocol.elements.draw_wire import WireContext


@pytest.fixture
def ctx() -> WireContext:
    return WireContext.for_indexed("line", 0)


class TestPoint2:
    def test_constructs_with_floats(self) -> None:
        p = Point2(x=1.0, y=2.5)
        assert (p.x, p.y) == (1.0, 2.5)

    def test_to_list_returns_xy(self) -> None:
        assert Point2(3.0, 4.0).to_list() == [3.0, 4.0]

    def test_from_wire_accepts_list(self, ctx: WireContext) -> None:
        assert Point2.from_wire([1, 2], ctx=ctx, field="p1") == Point2(1.0, 2.0)

    def test_from_wire_accepts_tuple(self, ctx: WireContext) -> None:
        assert Point2.from_wire((1, 2), ctx=ctx, field="p1") == Point2(1.0, 2.0)

    def test_from_wire_rejects_wrong_length(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match=r"\[x, y\] number pair"):
            Point2.from_wire([1, 2, 3], ctx=ctx, field="p1")

    def test_from_wire_rejects_non_numeric(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match=r"\[x, y\] number pair"):
            Point2.from_wire([1, "two"], ctx=ctx, field="p1")

    def test_from_wire_rejects_non_sequence(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match=r"\[x, y\] number pair"):
            Point2.from_wire("nope", ctx=ctx, field="p1")

    def test_from_wire_rejects_bool_coordinate(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match=r"\[x, y\] number pair"):
            Point2.from_wire([True, 1], ctx=ctx, field="p1")


class TestColor:
    def test_accepts_rgb(self) -> None:
        assert Color("#FF0000").value == "#FF0000"

    def test_accepts_rgba(self) -> None:
        assert Color("#FF000080").value == "#FF000080"

    def test_rejects_missing_hash(self) -> None:
        with pytest.raises(ValueError, match="hex string"):
            Color("FF0000")

    def test_rejects_wrong_length(self) -> None:
        with pytest.raises(ValueError, match="hex string"):
            Color("#FF00")

    def test_rejects_non_hex(self) -> None:
        with pytest.raises(ValueError, match="hex string"):
            Color("#GGGGGG")

    def test_from_wire_passes_through(self, ctx: WireContext) -> None:
        assert Color.from_wire("#00FF00", ctx=ctx, field="color") == Color("#00FF00")

    def test_from_wire_rejects_non_string(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="hex color"):
            Color.from_wire(0xFF0000, ctx=ctx, field="color")

    def test_from_wire_rejects_bad_hex(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="hex color"):
            Color.from_wire("red", ctx=ctx, field="color")

    def test_to_wire_returns_value(self) -> None:
        assert Color("#FFFFFF").to_wire() == "#FFFFFF"


class TestThickness:
    def test_accepts_positive(self) -> None:
        assert Thickness(2.5).value == 2.5

    def test_coerces_int(self) -> None:
        assert Thickness(3).value == 3.0

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="> 0"):
            Thickness(0)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="> 0"):
            Thickness(-1)

    def test_rejects_bool(self) -> None:
        with pytest.raises(ValueError, match="> 0"):
            Thickness(True)

    def test_from_wire_round_trips(self, ctx: WireContext) -> None:
        t = Thickness.from_wire(1.5, ctx=ctx, field="thickness")
        assert t.value == 1.5

    def test_from_wire_rejects_negative(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="> 0"):
            Thickness.from_wire(-1, ctx=ctx, field="thickness")
