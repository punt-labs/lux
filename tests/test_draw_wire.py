"""Tests for ``WireContext`` and the pure decode helpers."""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.draw_wire import (
    WireContext,
    coerce_number,
    object_sequence,
)


@pytest.fixture
def ctx() -> WireContext:
    return WireContext(kind="line", index=0)


class TestWireContext:
    def test_prefix_with_index(self) -> None:
        assert WireContext("circle", 3).prefix == "draw command [3] (circle)"

    def test_prefix_without_index(self) -> None:
        assert WireContext("circle").prefix == "draw command (circle)"

    def test_field_error_format(self) -> None:
        err = WireContext("circle", 2).field_error("radius", "a number > 0", -1)
        msg = str(err)
        assert "draw command [2] (circle)" in msg
        assert "'radius'" in msg
        assert "> 0" in msg
        assert "-1" in msg

    def test_require_field_present(self, ctx: WireContext) -> None:
        assert ctx.require_field({"a": 1}, "a") == 1

    def test_require_field_missing(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="missing required field 'a'"):
            ctx.require_field({}, "a")

    def test_require_bool_accepts_true(self, ctx: WireContext) -> None:
        assert ctx.require_bool(True, "f") is True

    def test_require_bool_rejects_int(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="bool"):
            ctx.require_bool(1, "f")

    def test_require_string_accepts_str(self, ctx: WireContext) -> None:
        assert ctx.require_string("hi", "f") == "hi"

    def test_require_string_rejects_int(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="string"):
            ctx.require_string(1, "f")


class TestPureHelpers:
    def test_coerce_number_accepts_int_and_float(self) -> None:
        assert coerce_number(1) == 1.0
        assert coerce_number(1.5) == 1.5

    def test_coerce_number_rejects_bool(self) -> None:
        assert coerce_number(True) is None

    def test_coerce_number_rejects_string(self) -> None:
        assert coerce_number("1") is None

    def test_object_sequence_returns_tuple(self) -> None:
        assert object_sequence([1, 2]) == (1, 2)
        assert object_sequence((1, 2)) == (1, 2)

    def test_object_sequence_rejects_other(self) -> None:
        assert object_sequence("ab") is None
        assert object_sequence(1) is None
