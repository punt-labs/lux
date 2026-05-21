"""Tests for ``Radius`` and ``Rounding`` bounded value classes."""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.draw_bounds import Radius, Rounding
from punt_lux.protocol.elements.draw_wire import WireContext


@pytest.fixture
def ctx() -> WireContext:
    return WireContext.for_indexed("circle", 0)


class TestRadius:
    def test_accepts_positive(self) -> None:
        assert Radius(5.0).value == 5.0

    def test_coerces_int(self) -> None:
        assert Radius(7).value == 7.0

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="> 0"):
            Radius(0)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="> 0"):
            Radius(-1)

    def test_rejects_bool(self) -> None:
        with pytest.raises(ValueError, match="> 0"):
            Radius(True)

    def test_from_wire_round_trips(self, ctx: WireContext) -> None:
        r = Radius.from_wire(2.5, ctx=ctx, field="radius")
        assert r.value == 2.5

    def test_from_wire_rejects_negative(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="> 0"):
            Radius.from_wire(-1, ctx=ctx, field="radius")

    def test_to_wire_returns_value(self) -> None:
        assert Radius(3.0).to_wire() == 3.0


class TestRounding:
    def test_accepts_zero(self) -> None:
        assert Rounding(0).value == 0.0

    def test_accepts_positive(self) -> None:
        assert Rounding(4.0).value == 4.0

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match=">= 0"):
            Rounding(-1)

    def test_rejects_bool(self) -> None:
        # True coerces to 1 silently through `int <= float` — must be rejected
        # explicitly so to_wire() doesn't return True instead of a float.
        with pytest.raises(ValueError, match=">= 0"):
            Rounding(True)

    def test_from_wire_accepts_zero(self, ctx: WireContext) -> None:
        r = Rounding.from_wire(0, ctx=ctx, field="rounding")
        assert r.value == 0.0

    def test_from_wire_rejects_negative(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match=">= 0"):
            Rounding.from_wire(-1, ctx=ctx, field="rounding")

    def test_to_wire_returns_value(self) -> None:
        assert Rounding(2.0).to_wire() == 2.0
