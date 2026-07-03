"""Tests for the hex colour parsers — valid forms, fallbacks, and warnings."""

from __future__ import annotations

import logging

import pytest

from punt_lux.display.renderers._color import parse_hex_color, parse_rgba


def test_parse_hex_color_six_digit() -> None:
    result = parse_hex_color("#FF8000")
    assert result is not None
    assert result == pytest.approx((1.0, 128 / 255, 0.0, 1.0))


def test_parse_hex_color_eight_digit_with_alpha() -> None:
    result = parse_hex_color("#FF800080")
    assert result is not None
    assert result == pytest.approx((1.0, 128 / 255, 0.0, 128 / 255))


def test_parse_hex_color_accepts_unprefixed() -> None:
    assert parse_hex_color("FFFFFF") == (1.0, 1.0, 1.0, 1.0)


def test_parse_hex_color_invalid_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Invalid hex must return None so renderers preserve theme.

    The prior contract returned opaque white on bad input, which made
    every styled text widget render white instead of the ImGui theme
    default.  Restoring ``| None`` lets renderers guard the push:
    ``if color is not None: push_style_color(...)``.
    """
    with caplog.at_level(logging.WARNING, logger="punt_lux.display.renderers._color"):
        result = parse_hex_color("#ZZZZZZ")
    assert result is None
    assert any("invalid hex color" in r.getMessage() for r in caplog.records)


def test_parse_hex_color_wrong_length_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="punt_lux.display.renderers._color"):
        result = parse_hex_color("#FFF")
    assert result is None
    assert any("not 6/8 hex digits" in r.getMessage() for r in caplog.records)


def test_parse_rgba_falls_back_to_white_on_invalid() -> None:
    """``parse_rgba`` keeps the opaque-white fallback — int callers need a tuple."""
    assert parse_rgba("not-a-color") == (255, 255, 255, 255)


def test_parse_rgba_six_digit() -> None:
    assert parse_rgba("#FF8000") == (255, 128, 0, 255)
