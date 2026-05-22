"""Tests for ``WireContext``."""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.draw_wire import WireContext


@pytest.fixture
def ctx() -> WireContext:
    return WireContext.for_indexed("line", 0)


class TestWireContextFactories:
    def test_at_index_prefix(self) -> None:
        assert WireContext.at_index(3).prefix == "draw command [3]"

    def test_for_indexed_prefix(self) -> None:
        assert (
            WireContext.for_indexed("circle", 2).prefix == "draw command [2] (circle)"
        )


class TestFieldError:
    def test_format(self) -> None:
        ctx = WireContext.for_indexed("circle", 2)
        err = ctx.field_error("radius", "a number > 0", -1)
        msg = str(err)
        assert "draw command [2] (circle)" in msg
        assert "'radius'" in msg
        assert "> 0" in msg
        assert "-1" in msg


class TestRequireField:
    def test_present(self, ctx: WireContext) -> None:
        assert ctx.require_field({"a": 1}, "a") == 1

    def test_missing(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="missing required field 'a'"):
            ctx.require_field({}, "a")


class TestRequireBool:
    def test_accepts_true(self, ctx: WireContext) -> None:
        assert ctx.require_bool(True, "f") is True

    def test_accepts_false(self, ctx: WireContext) -> None:
        assert ctx.require_bool(False, "f") is False

    def test_rejects_int(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="bool"):
            ctx.require_bool(1, "f")

    def test_rejects_string(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="bool"):
            ctx.require_bool("true", "f")


class TestOptionalBool:
    def test_uses_default_when_absent(self, ctx: WireContext) -> None:
        assert ctx.optional_bool({}, "f", default=True) is True
        assert ctx.optional_bool({}, "f", default=False) is False

    def test_uses_value_when_present(self, ctx: WireContext) -> None:
        assert ctx.optional_bool({"f": False}, "f", default=True) is False

    def test_rejects_non_bool(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="bool"):
            ctx.optional_bool({"f": 1}, "f", default=False)


class TestRequireString:
    def test_accepts_str(self, ctx: WireContext) -> None:
        assert ctx.require_string("hi", "f") == "hi"

    def test_rejects_int(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="string"):
            ctx.require_string(1, "f")


class TestRequireNumber:
    def test_accepts_int(self, ctx: WireContext) -> None:
        assert ctx.require_number(3, "f") == 3.0

    def test_accepts_float(self, ctx: WireContext) -> None:
        assert ctx.require_number(2.5, "f") == 2.5

    def test_rejects_bool(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="number"):
            ctx.require_number(True, "f")

    def test_rejects_string(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="number"):
            ctx.require_number("1", "f")

    def test_rejects_none(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="number"):
            ctx.require_number(None, "f")


class TestRequireSequence:
    def test_accepts_list(self, ctx: WireContext) -> None:
        assert ctx.require_sequence([1, 2], "f") == (1, 2)

    def test_accepts_tuple(self, ctx: WireContext) -> None:
        assert ctx.require_sequence((1, 2), "f") == (1, 2)

    def test_rejects_string(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="list or tuple"):
            ctx.require_sequence("ab", "f")

    def test_rejects_int(self, ctx: WireContext) -> None:
        with pytest.raises(ValueError, match="list or tuple"):
            ctx.require_sequence(1, "f")


class TestForElementFactory:
    def test_prefix_is_kind_plus_element(self) -> None:
        assert WireContext.for_element("progress").prefix == "progress element"


class TestOptionalString:
    @pytest.fixture
    def elem_ctx(self) -> WireContext:
        return WireContext.for_element("text")

    def test_returns_default_when_absent(self, elem_ctx: WireContext) -> None:
        assert elem_ctx.optional_string({}, "label", default="x") == "x"

    def test_returns_value_when_present(self, elem_ctx: WireContext) -> None:
        assert elem_ctx.optional_string({"label": "hi"}, "label", default="x") == "hi"

    def test_rejects_non_string(self, elem_ctx: WireContext) -> None:
        with pytest.raises(ValueError, match=r"text element.*'label'"):
            elem_ctx.optional_string({"label": 42}, "label", default="x")


class TestOptionalNumber:
    @pytest.fixture
    def elem_ctx(self) -> WireContext:
        return WireContext.for_element("spinner")

    def test_returns_default_when_absent(self, elem_ctx: WireContext) -> None:
        assert elem_ctx.optional_number({}, "radius", default=16.0) == 16.0

    def test_coerces_int_to_float(self, elem_ctx: WireContext) -> None:
        assert elem_ctx.optional_number({"radius": 8}, "radius", default=16.0) == 8.0

    def test_returns_float_when_present(self, elem_ctx: WireContext) -> None:
        assert elem_ctx.optional_number({"radius": 4.5}, "radius", default=16.0) == 4.5

    def test_rejects_bool(self, elem_ctx: WireContext) -> None:
        with pytest.raises(ValueError, match=r"spinner element.*'radius'"):
            elem_ctx.optional_number({"radius": True}, "radius", default=1.0)

    def test_rejects_string(self, elem_ctx: WireContext) -> None:
        with pytest.raises(ValueError, match=r"spinner element.*'radius'"):
            elem_ctx.optional_number({"radius": "big"}, "radius", default=1.0)


class TestOptionalInt:
    @pytest.fixture
    def elem_ctx(self) -> WireContext:
        return WireContext.for_element("image")

    def test_returns_none_default_when_absent(self, elem_ctx: WireContext) -> None:
        assert elem_ctx.optional_int({}, "width") is None

    def test_returns_int_when_present(self, elem_ctx: WireContext) -> None:
        assert elem_ctx.optional_int({"width": 100}, "width") == 100

    def test_rejects_bool(self, elem_ctx: WireContext) -> None:
        with pytest.raises(ValueError, match=r"image element.*'width'"):
            elem_ctx.optional_int({"width": True}, "width")

    def test_rejects_float(self, elem_ctx: WireContext) -> None:
        with pytest.raises(ValueError, match=r"image element.*'width'"):
            elem_ctx.optional_int({"width": 1.5}, "width")

    def test_rejects_string(self, elem_ctx: WireContext) -> None:
        with pytest.raises(ValueError, match=r"image element.*'width'"):
            elem_ctx.optional_int({"width": "100"}, "width")


class TestOptionalNullableString:
    @pytest.fixture
    def elem_ctx(self) -> WireContext:
        return WireContext.for_element("text")

    def test_returns_none_when_absent(self, elem_ctx: WireContext) -> None:
        assert elem_ctx.optional_nullable_string({}, "style") is None

    def test_returns_value_when_present(self, elem_ctx: WireContext) -> None:
        assert (
            elem_ctx.optional_nullable_string({"style": "heading"}, "style")
            == "heading"
        )

    def test_rejects_non_string(self, elem_ctx: WireContext) -> None:
        with pytest.raises(ValueError, match=r"text element.*'style'"):
            elem_ctx.optional_nullable_string({"style": 5}, "style")
