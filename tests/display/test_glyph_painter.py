"""GlyphPainter — the disc paints on its window's own list, clipped to the window."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Self, final

from imgui_bundle import ImVec2

from punt_lux.display.menus.glyph_painter import GlyphPainter

_WINDOW = (ImVec2(100.0, 100.0), ImVec2(500.0, 400.0))
_DISC = (ImVec2(460.0, 104.0), ImVec2(472.0, 116.0))


@final
class _Draw:
    """Record calls in order, so the clip can be seen to bracket the painting."""

    calls: list[str]
    clip: tuple[ImVec2, ImVec2] | None
    intersect: bool | None
    __slots__ = ("calls", "clip", "intersect")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.calls = []
        self.clip = None
        self.intersect = None
        return self

    def push_clip_rect(
        self, low: ImVec2, high: ImVec2, *, intersect_with_current_clip_rect: bool
    ) -> None:
        self.calls.append("push")
        self.clip = (low, high)
        self.intersect = intersect_with_current_clip_rect

    def pop_clip_rect(self) -> None:
        self.calls.append("pop")

    def add_rect_filled(self, *_args: object) -> None:
        self.calls.append("rect")

    def add_text(self, *_args: object) -> None:
        self.calls.append("text")


@final
class _Style:
    def color_(self, name: str) -> str:
        return name


@final
class _Imgui:
    Col_ = SimpleNamespace(button="button", button_hovered="hovered", text="text")

    draw: _Draw
    fills: list[str]
    __slots__ = ("draw", "fills")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.draw = _Draw()
        self.fills = []
        return self

    def get_window_draw_list(self) -> _Draw:
        return self.draw

    def get_style(self) -> _Style:
        return _Style()

    def get_color_u32(self, name: str) -> int:
        self.fills.append(name)
        return 0

    def calc_text_size(self, _text: str) -> ImVec2:
        return ImVec2(4.0, 8.0)


def _painted(*, hovered: bool) -> _Imgui:
    imgui = _Imgui()
    GlyphPainter().paint(imgui, _WINDOW, _DISC, hovered=hovered)
    return imgui


def test_the_clip_rect_is_the_whole_window_not_intersected() -> None:
    draw = _painted(hovered=False).draw
    assert (draw.clip, draw.intersect) == (_WINDOW, False)


def test_the_clip_brackets_the_painting() -> None:
    assert _painted(hovered=False).draw.calls == ["push", "rect", "text", "pop"]


def test_a_hovered_disc_fills_with_the_hover_color() -> None:
    assert _painted(hovered=True).fills[0] == "hovered"


def test_an_unhovered_disc_fills_with_the_button_color() -> None:
    assert _painted(hovered=False).fills[0] == "button"
