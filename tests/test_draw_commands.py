"""Tests for typed ``*Cmd`` dataclasses and the ``DrawCommand`` Protocol."""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.draw_bounds import (
    NO_ROUNDING,
    Radius,
    Rounding,
)
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
from punt_lux.protocol.elements.draw_values import (
    DEFAULT_THICKNESS,
    WHITE,
    Color,
    Point2,
    Thickness,
)


class TestDrawCommandKind:
    def test_str_enum_values_match_wire(self) -> None:
        assert DrawCommandKind.LINE.value == "line"
        assert DrawCommandKind.RECT.value == "rect"
        assert DrawCommandKind.CIRCLE.value == "circle"
        assert DrawCommandKind.TRIANGLE.value == "triangle"
        assert DrawCommandKind.TEXT.value == "text"
        assert DrawCommandKind.POLYLINE.value == "polyline"
        assert DrawCommandKind.BEZIER_CUBIC.value == "bezier_cubic"

    def test_str_enum_round_trips_from_value(self) -> None:
        assert DrawCommandKind("circle") is DrawCommandKind.CIRCLE


class TestLine:
    def test_defaults(self) -> None:
        cmd = Line(p1=Point2(0, 0), p2=Point2(10, 10))
        assert cmd.kind is DrawCommandKind.LINE
        assert cmd.color is WHITE
        assert cmd.thickness is DEFAULT_THICKNESS

    def test_to_dict_shape(self) -> None:
        cmd = Line(p1=Point2(1, 2), p2=Point2(3, 4))
        assert cmd.to_dict() == {
            "cmd": "line",
            "p1": [1.0, 2.0],
            "p2": [3.0, 4.0],
            "color": "#FFFFFF",
            "thickness": 1.0,
        }

    def test_satisfies_draw_command_protocol(self) -> None:
        cmd = Line(p1=Point2(0, 0), p2=Point2(1, 1))
        assert isinstance(cmd, DrawCommand)


class TestRect:
    def test_defaults(self) -> None:
        cmd = Rect(min=Point2(0, 0), max=Point2(10, 10))
        assert cmd.kind is DrawCommandKind.RECT
        assert cmd.rounding is NO_ROUNDING
        assert cmd.filled is False

    def test_to_dict_shape(self) -> None:
        cmd = Rect(
            min=Point2(1, 2),
            max=Point2(3, 4),
            rounding=Rounding(2.0),
            filled=True,
        )
        assert cmd.to_dict() == {
            "cmd": "rect",
            "min": [1.0, 2.0],
            "max": [3.0, 4.0],
            "color": "#FFFFFF",
            "thickness": 1.0,
            "rounding": 2.0,
            "filled": True,
        }

    def test_satisfies_draw_command_protocol(self) -> None:
        assert isinstance(Rect(min=Point2(0, 0), max=Point2(1, 1)), DrawCommand)


class TestCircle:
    def test_defaults(self) -> None:
        cmd = Circle(center=Point2(5, 5), radius=Radius(2.5))
        assert cmd.kind is DrawCommandKind.CIRCLE
        assert cmd.filled is False

    def test_to_dict_shape(self) -> None:
        cmd = Circle(center=Point2(5, 5), radius=Radius(3), filled=True)
        assert cmd.to_dict() == {
            "cmd": "circle",
            "center": [5.0, 5.0],
            "radius": 3.0,
            "color": "#FFFFFF",
            "thickness": 1.0,
            "filled": True,
        }

    def test_satisfies_draw_command_protocol(self) -> None:
        cmd = Circle(center=Point2(0, 0), radius=Radius(1))
        assert isinstance(cmd, DrawCommand)


class TestTriangle:
    def test_defaults(self) -> None:
        cmd = Triangle(p1=Point2(0, 0), p2=Point2(1, 0), p3=Point2(0, 1))
        assert cmd.kind is DrawCommandKind.TRIANGLE
        assert cmd.filled is False

    def test_to_dict_shape(self) -> None:
        cmd = Triangle(
            p1=Point2(0, 0),
            p2=Point2(1, 0),
            p3=Point2(0, 1),
            color=Color("#FF0000"),
            thickness=Thickness(2),
            filled=True,
        )
        assert cmd.to_dict() == {
            "cmd": "triangle",
            "p1": [0.0, 0.0],
            "p2": [1.0, 0.0],
            "p3": [0.0, 1.0],
            "color": "#FF0000",
            "thickness": 2.0,
            "filled": True,
        }

    def test_satisfies_draw_command_protocol(self) -> None:
        cmd = Triangle(p1=Point2(0, 0), p2=Point2(1, 0), p3=Point2(0, 1))
        assert isinstance(cmd, DrawCommand)


class TestTextGlyph:
    def test_defaults(self) -> None:
        cmd = TextGlyph(pos=Point2(0, 0), text="hello")
        assert cmd.kind is DrawCommandKind.TEXT
        assert cmd.color is WHITE

    def test_to_dict_shape(self) -> None:
        cmd = TextGlyph(pos=Point2(5, 10), text="hi", color=Color("#00FF00"))
        assert cmd.to_dict() == {
            "cmd": "text",
            "pos": [5.0, 10.0],
            "text": "hi",
            "color": "#00FF00",
        }

    def test_allows_empty_text(self) -> None:
        # Text content is not the wire boundary's concern; empty is legal at
        # this layer. The validator is the place to reject if needed.
        TextGlyph(pos=Point2(0, 0), text="")

    def test_satisfies_draw_command_protocol(self) -> None:
        assert isinstance(TextGlyph(pos=Point2(0, 0), text="x"), DrawCommand)


class TestPolyline:
    def test_minimum_two_points(self) -> None:
        cmd = Polyline(points=(Point2(0, 0), Point2(1, 1)))
        assert cmd.kind is DrawCommandKind.POLYLINE
        assert cmd.closed is False
        assert len(cmd.points) == 2

    def test_rejects_zero_points(self) -> None:
        with pytest.raises(ValueError, match="at least 2 points"):
            Polyline(points=())

    def test_rejects_single_point(self) -> None:
        with pytest.raises(ValueError, match="at least 2 points"):
            Polyline(points=(Point2(0, 0),))

    def test_to_dict_shape(self) -> None:
        cmd = Polyline(
            points=(Point2(0, 0), Point2(1, 1), Point2(2, 0)),
            closed=True,
        )
        assert cmd.to_dict() == {
            "cmd": "polyline",
            "points": [[0.0, 0.0], [1.0, 1.0], [2.0, 0.0]],
            "color": "#FFFFFF",
            "thickness": 1.0,
            "closed": True,
        }

    def test_satisfies_draw_command_protocol(self) -> None:
        cmd = Polyline(points=(Point2(0, 0), Point2(1, 1)))
        assert isinstance(cmd, DrawCommand)


class TestBezierCubic:
    def test_defaults(self) -> None:
        cmd = BezierCubic(
            p1=Point2(0, 0),
            p2=Point2(1, 0),
            p3=Point2(2, 1),
            p4=Point2(3, 1),
        )
        assert cmd.kind is DrawCommandKind.BEZIER_CUBIC
        assert cmd.color is WHITE

    def test_to_dict_shape(self) -> None:
        cmd = BezierCubic(
            p1=Point2(0, 0),
            p2=Point2(1, 0),
            p3=Point2(2, 1),
            p4=Point2(3, 1),
        )
        assert cmd.to_dict() == {
            "cmd": "bezier_cubic",
            "p1": [0.0, 0.0],
            "p2": [1.0, 0.0],
            "p3": [2.0, 1.0],
            "p4": [3.0, 1.0],
            "color": "#FFFFFF",
            "thickness": 1.0,
        }

    def test_satisfies_draw_command_protocol(self) -> None:
        cmd = BezierCubic(
            p1=Point2(0, 0),
            p2=Point2(1, 0),
            p3=Point2(2, 1),
            p4=Point2(3, 1),
        )
        assert isinstance(cmd, DrawCommand)


class TestDrawCommandProtocol:
    """The Protocol is the family contract — every concrete kind satisfies it."""

    def test_every_concrete_command_is_a_draw_command(self) -> None:
        # one of each kind; verifies structural conformance across the family
        commands = [
            Line(p1=Point2(0, 0), p2=Point2(1, 1)),
            Rect(min=Point2(0, 0), max=Point2(1, 1)),
            Circle(center=Point2(0, 0), radius=Radius(1)),
            Triangle(p1=Point2(0, 0), p2=Point2(1, 0), p3=Point2(0, 1)),
            TextGlyph(pos=Point2(0, 0), text="x"),
            Polyline(points=(Point2(0, 0), Point2(1, 1))),
            BezierCubic(
                p1=Point2(0, 0),
                p2=Point2(1, 0),
                p3=Point2(2, 1),
                p4=Point2(3, 1),
            ),
        ]
        for cmd in commands:
            assert isinstance(cmd, DrawCommand)
            assert cmd.kind.value == cmd.to_dict()["cmd"]
