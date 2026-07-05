# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Render a ``DrawElement``'s command list onto an ImGui draw list.

Owns the whole draw-command surface: canvas setup, the per-command match
dispatch, the seven primitive painters, and the color helpers those
painters need. Split out of ``ElementRenderer`` so the general element
dispatch and the draw subsystem each stay one responsibility (PY-IC-6).
"""

from __future__ import annotations

import logging
from typing import Any, Self, final

from imgui_bundle import ImVec2, ImVec4, imgui

from punt_lux.protocol.elements.draw_command_kind import DrawCommand
from punt_lux.protocol.elements.draw_commands_curve import BezierCubic
from punt_lux.protocol.elements.draw_commands_line import Line, Polyline
from punt_lux.protocol.elements.draw_commands_shape import Circle, Rect, Triangle
from punt_lux.protocol.elements.draw_commands_text import TextGlyph
from punt_lux.protocol.elements.graphics import DrawElement

__all__ = ["DrawElementRenderer"]

logger = logging.getLogger(__name__)


@final
class DrawElementRenderer:
    """Paint a ``DrawElement`` — canvas, command dispatch, and primitives."""

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def render(self, elem: DrawElement) -> None:
        """Paint ``elem``'s background and command list within its canvas."""
        canvas_pos = imgui.get_cursor_screen_pos()
        canvas_min = ImVec2(canvas_pos.x, canvas_pos.y)
        canvas_max = ImVec2(canvas_pos.x + elem.width, canvas_pos.y + elem.height)
        draw_list = imgui.get_window_draw_list()

        draw_list.push_clip_rect(canvas_min, canvas_max, True)  # noqa: FBT003

        if elem.bg_color is not None:
            draw_list.add_rect_filled(
                canvas_min, canvas_max, self._to_imgui_color(elem.bg_color)
            )

        ox, oy = canvas_pos.x, canvas_pos.y
        # Wire decoding ran in DrawCommandDecoder; the renderer cannot
        # receive a malformed command. A prior try/except that swallowed
        # KeyError/IndexError/TypeError/ValueError masked the silent-default
        # bug the typed decoder now prevents at the wire boundary.
        for cmd in elem.commands:
            self._dispatch_draw_cmd(draw_list, cmd, ox, oy)

        draw_list.pop_clip_rect()
        imgui.dummy(ImVec2(elem.width, elem.height))

    def _dispatch_draw_cmd(
        self,
        draw_list: Any,
        cmd: DrawCommand,
        ox: float,
        oy: float,
    ) -> None:
        match cmd:
            case Line():
                self._draw_line(draw_list, cmd, ox, oy)
            case Rect():
                self._draw_rect(draw_list, cmd, ox, oy)
            case Circle():
                self._draw_circle(draw_list, cmd, ox, oy)
            case Triangle():
                self._draw_triangle(draw_list, cmd, ox, oy)
            case TextGlyph():
                self._draw_text(draw_list, cmd, ox, oy)
            case Polyline():
                self._draw_polyline(draw_list, cmd, ox, oy)
            case BezierCubic():
                self._draw_bezier(draw_list, cmd, ox, oy)
            case _:
                # Unreachable in normal use — DrawCommand is the closed union
                # of the typed records registered with the decoder. Raise so a
                # new kind added without renderer support fails loud rather
                # than silently rendering nothing.
                msg = f"unhandled draw command kind: {type(cmd).__name__}"
                raise TypeError(msg)

    def _draw_line(self, dl: Any, cmd: Line, ox: float, oy: float) -> None:
        dl.add_line(
            ImVec2(ox + cmd.p1.x, oy + cmd.p1.y),
            ImVec2(ox + cmd.p2.x, oy + cmd.p2.y),
            self._to_imgui_color(cmd.color.value),
            cmd.thickness.value,
        )

    def _draw_rect(self, dl: Any, cmd: Rect, ox: float, oy: float) -> None:
        color = self._to_imgui_color(cmd.color.value)
        lo = ImVec2(ox + cmd.min.x, oy + cmd.min.y)
        hi = ImVec2(ox + cmd.max.x, oy + cmd.max.y)
        if cmd.filled:
            dl.add_rect_filled(lo, hi, color, cmd.rounding.value)
        else:
            dl.add_rect(lo, hi, color, cmd.rounding.value, 0, cmd.thickness.value)

    def _draw_circle(self, dl: Any, cmd: Circle, ox: float, oy: float) -> None:
        color = self._to_imgui_color(cmd.color.value)
        center = ImVec2(ox + cmd.center.x, oy + cmd.center.y)
        if cmd.filled:
            dl.add_circle_filled(center, cmd.radius.value, color)
        else:
            dl.add_circle(center, cmd.radius.value, color, 0, cmd.thickness.value)

    def _draw_triangle(self, dl: Any, cmd: Triangle, ox: float, oy: float) -> None:
        color = self._to_imgui_color(cmd.color.value)
        p1 = ImVec2(ox + cmd.p1.x, oy + cmd.p1.y)
        p2 = ImVec2(ox + cmd.p2.x, oy + cmd.p2.y)
        p3 = ImVec2(ox + cmd.p3.x, oy + cmd.p3.y)
        if cmd.filled:
            dl.add_triangle_filled(p1, p2, p3, color)
        else:
            dl.add_triangle(p1, p2, p3, color, cmd.thickness.value)

    def _draw_text(self, dl: Any, cmd: TextGlyph, ox: float, oy: float) -> None:
        color = self._to_imgui_color(cmd.color.value)
        dl.add_text(ImVec2(ox + cmd.pos.x, oy + cmd.pos.y), color, cmd.text)

    def _draw_polyline(self, dl: Any, cmd: Polyline, ox: float, oy: float) -> None:
        im_draw_flags_closed = 1
        color = self._to_imgui_color(cmd.color.value)
        points = [ImVec2(ox + p.x, oy + p.y) for p in cmd.points]
        flags = im_draw_flags_closed if cmd.closed else 0
        dl.add_polyline(points, color, flags, cmd.thickness.value)

    def _draw_bezier(self, dl: Any, cmd: BezierCubic, ox: float, oy: float) -> None:
        dl.add_bezier_cubic(
            ImVec2(ox + cmd.p1.x, oy + cmd.p1.y),
            ImVec2(ox + cmd.p2.x, oy + cmd.p2.y),
            ImVec2(ox + cmd.p3.x, oy + cmd.p3.y),
            ImVec2(ox + cmd.p4.x, oy + cmd.p4.y),
            self._to_imgui_color(cmd.color.value),
            cmd.thickness.value,
        )

    # -- color helpers ---------------------------------------------------------

    @staticmethod
    def _parse_color(
        color: str | list[int] | tuple[int, ...] | Any,
    ) -> tuple[int, int, int, int]:
        """Parse a color value to (r, g, b, a) ints 0-255."""
        if isinstance(color, (list, tuple)):
            try:
                if len(color) >= 4:
                    return (
                        int(color[0]),
                        int(color[1]),
                        int(color[2]),
                        int(color[3]),
                    )
                if len(color) == 3:
                    return (int(color[0]), int(color[1]), int(color[2]), 255)
            except (TypeError, ValueError):
                pass
            logger.warning("Invalid RGBA color %r; using fallback white", color)
            return (255, 255, 255, 255)
        if not isinstance(color, str):
            logger.warning("Invalid color type %r; using fallback white", type(color))
            return (255, 255, 255, 255)
        h = color.lstrip("#")
        try:
            if len(h) == 6:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
            if len(h) == 8:
                return (
                    int(h[0:2], 16),
                    int(h[2:4], 16),
                    int(h[4:6], 16),
                    int(h[6:8], 16),
                )
        except ValueError:
            logger.warning("Invalid hex color %r; using fallback white", color)
        return (255, 255, 255, 255)

    @staticmethod
    def _to_imgui_color(color: str | list[int] | tuple[int, ...] | Any) -> int:
        """Convert a color value to ImGui packed color (ImU32)."""
        r, g, b, a = DrawElementRenderer._parse_color(color)
        result: int = imgui.get_color_u32(
            ImVec4(r / 255.0, g / 255.0, b / 255.0, a / 255.0)
        )
        return result
