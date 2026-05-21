"""Tests for ``DrawCommandDecoder`` and ``DrawCommandDecoder.default()``."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from punt_lux.protocol.elements.draw_bounds import Radius
from punt_lux.protocol.elements.draw_command_kind import (
    DrawCommand,
    DrawCommandKind,
)
from punt_lux.protocol.elements.draw_commands_curve import BezierCubic
from punt_lux.protocol.elements.draw_commands_line import Line, Polyline
from punt_lux.protocol.elements.draw_commands_shape import (
    Circle,
    Rect,
    Triangle,
)
from punt_lux.protocol.elements.draw_commands_text import TextGlyph
from punt_lux.protocol.elements.draw_decoder import DrawCommandDecoder
from punt_lux.protocol.elements.draw_values import Point2
from punt_lux.protocol.elements.draw_wire import WireContext


def _decode(wire: Mapping[str, object], *, index: int = 0) -> DrawCommand:
    """Tiny test helper — exercises the populated default singleton."""
    return DrawCommandDecoder.default().decode(wire, index)


class TestDefaultDecoderHappyPath:
    """Each wire-kind decodes to the matching typed command."""

    def test_line(self) -> None:
        wire = {
            "cmd": "line",
            "p1": [0, 0],
            "p2": [10, 5],
            "color": "#00FF00",
            "thickness": 2,
        }
        cmd = _decode(wire)
        assert isinstance(cmd, Line)
        assert cmd.p1.x == 0.0
        assert cmd.p2.x == 10.0

    def test_rect(self) -> None:
        wire = {
            "cmd": "rect",
            "min": [0, 0],
            "max": [10, 10],
            "rounding": 2,
            "filled": True,
        }
        cmd = _decode(wire)
        assert isinstance(cmd, Rect)
        assert cmd.rounding.value == 2.0
        assert cmd.filled is True

    def test_circle(self) -> None:
        wire = {"cmd": "circle", "center": [5, 5], "radius": 3}
        cmd = _decode(wire)
        assert isinstance(cmd, Circle)
        assert cmd.center.x == 5.0
        assert cmd.radius.value == 3.0

    def test_triangle(self) -> None:
        wire = {
            "cmd": "triangle",
            "p1": [0, 0],
            "p2": [1, 0],
            "p3": [0, 1],
            "filled": True,
        }
        cmd = _decode(wire)
        assert isinstance(cmd, Triangle)
        assert cmd.filled is True

    def test_text(self) -> None:
        wire = {"cmd": "text", "pos": [5, 5], "text": "hello"}
        cmd = _decode(wire)
        assert isinstance(cmd, TextGlyph)
        assert cmd.text == "hello"

    def test_polyline(self) -> None:
        wire = {
            "cmd": "polyline",
            "points": [[0, 0], [1, 1], [2, 0]],
            "closed": True,
        }
        cmd = _decode(wire)
        assert isinstance(cmd, Polyline)
        assert len(cmd.points) == 3
        assert cmd.closed is True

    def test_bezier_cubic(self) -> None:
        wire = {
            "cmd": "bezier_cubic",
            "p1": [0, 0],
            "p2": [1, 0],
            "p3": [2, 1],
            "p4": [3, 1],
        }
        cmd = _decode(wire)
        assert isinstance(cmd, BezierCubic)

    def test_returns_value_satisfies_draw_command(self) -> None:
        cmd = _decode({"cmd": "circle", "center": [0, 0], "radius": 1})
        assert isinstance(cmd, DrawCommand)


class TestDecoderErrors:
    def test_missing_cmd_field(self) -> None:
        with pytest.raises(ValueError, match="missing or invalid 'cmd'"):
            _decode({"center": [0, 0], "radius": 1})

    def test_empty_cmd_field(self) -> None:
        with pytest.raises(ValueError, match="missing or invalid 'cmd'"):
            _decode({"cmd": ""})

    def test_unknown_cmd_value(self) -> None:
        with pytest.raises(ValueError, match=r"unknown 'cmd' 'arc'"):
            _decode({"cmd": "arc"})

    def test_missing_required_field(self) -> None:
        with pytest.raises(ValueError, match=r"missing required field 'radius'"):
            _decode({"cmd": "circle", "center": [0, 0]})

    def test_invalid_point(self) -> None:
        with pytest.raises(ValueError, match=r"\[x, y\] number pair"):
            _decode({"cmd": "circle", "center": "nope", "radius": 1})

    def test_invalid_radius(self) -> None:
        with pytest.raises(ValueError, match=r"number > 0"):
            _decode({"cmd": "circle", "center": [0, 0], "radius": 0})

    def test_polyline_too_few_points(self) -> None:
        with pytest.raises(ValueError, match="at least 2 points"):
            _decode({"cmd": "polyline", "points": [[0, 0]]})

    def test_polyline_points_not_a_sequence(self) -> None:
        with pytest.raises(ValueError, match="list or tuple"):
            _decode({"cmd": "polyline", "points": "nope"})

    def test_text_missing_text_field(self) -> None:
        with pytest.raises(ValueError, match=r"missing required field 'text'"):
            _decode({"cmd": "text", "pos": [0, 0]})

    def test_text_non_string(self) -> None:
        with pytest.raises(ValueError, match="must be string"):
            _decode({"cmd": "text", "pos": [0, 0], "text": 5})

    def test_error_includes_index(self) -> None:
        with pytest.raises(ValueError, match=r"draw command \[3\] \(circle\)"):
            _decode({"cmd": "circle"}, index=3)


class TestDecoderRegistry:
    def test_fresh_decoder_has_no_kinds(self) -> None:
        assert DrawCommandDecoder().registered_kinds == frozenset()

    def test_default_decoder_registers_every_kind(self) -> None:
        assert DrawCommandDecoder.default().registered_kinds == frozenset(
            DrawCommandKind
        )

    def test_default_decoder_returns_same_singleton(self) -> None:
        assert DrawCommandDecoder.default() is DrawCommandDecoder.default()

    def test_register_rejects_duplicate(self) -> None:
        decoder = DrawCommandDecoder()
        sentinel = Circle(center=Point2(0, 0), radius=Radius(1))

        def stub(d: Mapping[str, object], *, ctx: WireContext) -> DrawCommand:
            _ = d, ctx
            return sentinel

        decoder.register(DrawCommandKind.CIRCLE, stub)
        with pytest.raises(ValueError, match="already registered"):
            decoder.register(DrawCommandKind.CIRCLE, stub)


class TestMotivatingBug:
    """Regression — agent sends wrong field names, must fail loud."""

    def test_circle_with_op_x_y_r_fails(self) -> None:
        # Real wire payload that previously silent-defaulted to a
        # white circle at the origin with radius 10.
        bad = {"op": "circle", "x": 100, "y": 100, "r": 40}
        with pytest.raises(ValueError, match="missing or invalid 'cmd'"):
            _decode(bad)
