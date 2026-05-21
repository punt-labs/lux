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
from punt_lux.protocol.elements.draw_commands_curve import BezierCubicCmd
from punt_lux.protocol.elements.draw_commands_line import LineCmd, PolylineCmd
from punt_lux.protocol.elements.draw_commands_shape import (
    CircleCmd,
    RectCmd,
    TriangleCmd,
)
from punt_lux.protocol.elements.draw_commands_text import TextCmd
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


class TestLineCmd:
    def test_defaults(self) -> None:
        cmd = LineCmd(p1=Point2(0, 0), p2=Point2(10, 10))
        assert cmd.kind is DrawCommandKind.LINE
        assert cmd.color is WHITE
        assert cmd.thickness is DEFAULT_THICKNESS

    def test_to_dict_shape(self) -> None:
        cmd = LineCmd(p1=Point2(1, 2), p2=Point2(3, 4))
        assert cmd.to_dict() == {
            "cmd": "line",
            "p1": [1.0, 2.0],
            "p2": [3.0, 4.0],
            "color": "#FFFFFF",
            "thickness": 1.0,
        }

    def test_satisfies_draw_command_protocol(self) -> None:
        cmd = LineCmd(p1=Point2(0, 0), p2=Point2(1, 1))
        assert isinstance(cmd, DrawCommand)


class TestRectCmd:
    def test_defaults(self) -> None:
        cmd = RectCmd(min=Point2(0, 0), max=Point2(10, 10))
        assert cmd.kind is DrawCommandKind.RECT
        assert cmd.rounding is NO_ROUNDING
        assert cmd.filled is False

    def test_to_dict_shape(self) -> None:
        cmd = RectCmd(
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
        assert isinstance(RectCmd(min=Point2(0, 0), max=Point2(1, 1)), DrawCommand)


class TestCircleCmd:
    def test_defaults(self) -> None:
        cmd = CircleCmd(center=Point2(5, 5), radius=Radius(2.5))
        assert cmd.kind is DrawCommandKind.CIRCLE
        assert cmd.filled is False

    def test_to_dict_shape(self) -> None:
        cmd = CircleCmd(center=Point2(5, 5), radius=Radius(3), filled=True)
        assert cmd.to_dict() == {
            "cmd": "circle",
            "center": [5.0, 5.0],
            "radius": 3.0,
            "color": "#FFFFFF",
            "thickness": 1.0,
            "filled": True,
        }

    def test_satisfies_draw_command_protocol(self) -> None:
        cmd = CircleCmd(center=Point2(0, 0), radius=Radius(1))
        assert isinstance(cmd, DrawCommand)


class TestTriangleCmd:
    def test_defaults(self) -> None:
        cmd = TriangleCmd(p1=Point2(0, 0), p2=Point2(1, 0), p3=Point2(0, 1))
        assert cmd.kind is DrawCommandKind.TRIANGLE
        assert cmd.filled is False

    def test_to_dict_shape(self) -> None:
        cmd = TriangleCmd(
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
        cmd = TriangleCmd(p1=Point2(0, 0), p2=Point2(1, 0), p3=Point2(0, 1))
        assert isinstance(cmd, DrawCommand)


class TestTextCmd:
    def test_defaults(self) -> None:
        cmd = TextCmd(pos=Point2(0, 0), text="hello")
        assert cmd.kind is DrawCommandKind.TEXT
        assert cmd.color is WHITE

    def test_to_dict_shape(self) -> None:
        cmd = TextCmd(pos=Point2(5, 10), text="hi", color=Color("#00FF00"))
        assert cmd.to_dict() == {
            "cmd": "text",
            "pos": [5.0, 10.0],
            "text": "hi",
            "color": "#00FF00",
        }

    def test_allows_empty_text(self) -> None:
        # Text content is not the wire boundary's concern; empty is legal at
        # this layer. The validator is the place to reject if needed.
        TextCmd(pos=Point2(0, 0), text="")

    def test_satisfies_draw_command_protocol(self) -> None:
        assert isinstance(TextCmd(pos=Point2(0, 0), text="x"), DrawCommand)


class TestPolylineCmd:
    def test_minimum_two_points(self) -> None:
        cmd = PolylineCmd(points=(Point2(0, 0), Point2(1, 1)))
        assert cmd.kind is DrawCommandKind.POLYLINE
        assert cmd.closed is False
        assert len(cmd.points) == 2

    def test_rejects_zero_points(self) -> None:
        with pytest.raises(ValueError, match="at least 2 points"):
            PolylineCmd(points=())

    def test_rejects_single_point(self) -> None:
        with pytest.raises(ValueError, match="at least 2 points"):
            PolylineCmd(points=(Point2(0, 0),))

    def test_to_dict_shape(self) -> None:
        cmd = PolylineCmd(
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
        cmd = PolylineCmd(points=(Point2(0, 0), Point2(1, 1)))
        assert isinstance(cmd, DrawCommand)


class TestBezierCubicCmd:
    def test_defaults(self) -> None:
        cmd = BezierCubicCmd(
            p1=Point2(0, 0),
            p2=Point2(1, 0),
            p3=Point2(2, 1),
            p4=Point2(3, 1),
        )
        assert cmd.kind is DrawCommandKind.BEZIER_CUBIC
        assert cmd.color is WHITE

    def test_to_dict_shape(self) -> None:
        cmd = BezierCubicCmd(
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
        cmd = BezierCubicCmd(
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
            LineCmd(p1=Point2(0, 0), p2=Point2(1, 1)),
            RectCmd(min=Point2(0, 0), max=Point2(1, 1)),
            CircleCmd(center=Point2(0, 0), radius=Radius(1)),
            TriangleCmd(p1=Point2(0, 0), p2=Point2(1, 0), p3=Point2(0, 1)),
            TextCmd(pos=Point2(0, 0), text="x"),
            PolylineCmd(points=(Point2(0, 0), Point2(1, 1))),
            BezierCubicCmd(
                p1=Point2(0, 0),
                p2=Point2(1, 0),
                p3=Point2(2, 1),
                p4=Point2(3, 1),
            ),
        ]
        for cmd in commands:
            assert isinstance(cmd, DrawCommand)
            assert cmd.kind.value == cmd.to_dict()["cmd"]
