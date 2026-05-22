"""Tests for ``ElementWireContext`` — the basics ``from_dict`` decode context."""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.element_wire import ElementWireContext


@pytest.fixture
def text_ctx() -> ElementWireContext:
    return ElementWireContext.for_kind("text")


@pytest.fixture
def spinner_ctx() -> ElementWireContext:
    return ElementWireContext.for_kind("spinner")


@pytest.fixture
def image_ctx() -> ElementWireContext:
    return ElementWireContext.for_kind("image")


class TestRequireStr:
    def test_returns_value_when_present(self, text_ctx: ElementWireContext) -> None:
        assert text_ctx.require_str({"id": "t1"}, "id") == "t1"

    def test_rejects_missing(self, text_ctx: ElementWireContext) -> None:
        with pytest.raises(ValueError, match=r"text element.*'id'"):
            text_ctx.require_str({}, "id")

    def test_rejects_non_string(self, text_ctx: ElementWireContext) -> None:
        with pytest.raises(ValueError, match=r"text element.*'id'"):
            text_ctx.require_str({"id": 7}, "id")


class TestRequireNumber:
    def test_returns_value_when_present(
        self, spinner_ctx: ElementWireContext
    ) -> None:
        assert spinner_ctx.require_number({"radius": 8.0}, "radius") == 8.0

    def test_coerces_int_to_float(self, spinner_ctx: ElementWireContext) -> None:
        assert spinner_ctx.require_number({"radius": 8}, "radius") == 8.0

    def test_rejects_missing(self, spinner_ctx: ElementWireContext) -> None:
        with pytest.raises(ValueError, match=r"spinner element.*'radius'"):
            spinner_ctx.require_number({}, "radius")

    def test_rejects_string(self, spinner_ctx: ElementWireContext) -> None:
        with pytest.raises(ValueError, match=r"spinner element.*'radius'"):
            spinner_ctx.require_number({"radius": "big"}, "radius")


class TestOptionalStr:
    def test_returns_default_when_absent(self, text_ctx: ElementWireContext) -> None:
        assert text_ctx.optional_str({}, "label", default="x") == "x"

    def test_returns_value_when_present(self, text_ctx: ElementWireContext) -> None:
        assert text_ctx.optional_str({"label": "hi"}, "label", default="x") == "hi"

    def test_rejects_non_string(self, text_ctx: ElementWireContext) -> None:
        with pytest.raises(ValueError, match=r"text element.*'label'"):
            text_ctx.optional_str({"label": 42}, "label", default="x")


class TestOptionalNumber:
    def test_returns_default_when_absent(
        self, spinner_ctx: ElementWireContext
    ) -> None:
        assert spinner_ctx.optional_number({}, "radius", default=16.0) == 16.0

    def test_coerces_int_to_float(self, spinner_ctx: ElementWireContext) -> None:
        assert (
            spinner_ctx.optional_number({"radius": 8}, "radius", default=16.0) == 8.0
        )

    def test_rejects_bool(self, spinner_ctx: ElementWireContext) -> None:
        with pytest.raises(ValueError, match=r"spinner element.*'radius'"):
            spinner_ctx.optional_number({"radius": True}, "radius", default=1.0)

    def test_rejects_string(self, spinner_ctx: ElementWireContext) -> None:
        with pytest.raises(ValueError, match=r"spinner element.*'radius'"):
            spinner_ctx.optional_number({"radius": "big"}, "radius", default=1.0)


class TestOptionalInt:
    def test_returns_none_when_absent(self, image_ctx: ElementWireContext) -> None:
        assert image_ctx.optional_int({}, "width") is None

    def test_returns_int_when_present(self, image_ctx: ElementWireContext) -> None:
        assert image_ctx.optional_int({"width": 100}, "width") == 100

    def test_rejects_bool(self, image_ctx: ElementWireContext) -> None:
        with pytest.raises(ValueError, match=r"image element.*'width'"):
            image_ctx.optional_int({"width": True}, "width")

    def test_rejects_float(self, image_ctx: ElementWireContext) -> None:
        with pytest.raises(ValueError, match=r"image element.*'width'"):
            image_ctx.optional_int({"width": 1.5}, "width")

    def test_rejects_string(self, image_ctx: ElementWireContext) -> None:
        with pytest.raises(ValueError, match=r"image element.*'width'"):
            image_ctx.optional_int({"width": "100"}, "width")


class TestOptionalNullableStr:
    def test_returns_none_when_absent(self, text_ctx: ElementWireContext) -> None:
        assert text_ctx.optional_nullable_str({}, "style") is None

    def test_returns_value_when_present(self, text_ctx: ElementWireContext) -> None:
        assert (
            text_ctx.optional_nullable_str({"style": "heading"}, "style") == "heading"
        )

    def test_rejects_non_string(self, text_ctx: ElementWireContext) -> None:
        with pytest.raises(ValueError, match=r"text element.*'style'"):
            text_ctx.optional_nullable_str({"style": 5}, "style")
