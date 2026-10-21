"""GlyphHit — the mouse counts on a glyph only while nothing covers its window."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Self, final

import pytest
from imgui_bundle import ImVec2

from punt_lux.display.menus.glyph_hit import GlyphHit

_LOW = ImVec2(10.0, 10.0)
_HIGH = ImVec2(20.0, 20.0)
_INSIDE = (15.0, 15.0)
_OUTSIDE = (50.0, 50.0)


@final
class _Imgui:
    """Scripts the mouse, this window's hover, and the window under the mouse."""

    HoveredFlags_ = SimpleNamespace(
        allow_when_blocked_by_popup=SimpleNamespace(value=8),
        allow_when_blocked_by_active_item=SimpleNamespace(value=32),
    )

    _mouse: tuple[float, float]
    _is_window_hovered: bool
    _under_mouse: SimpleNamespace | None
    flags_asked: int
    __slots__ = ("_is_window_hovered", "_mouse", "_under_mouse", "flags_asked")

    def __new__(
        cls,
        mouse: tuple[float, float],
        *,
        is_window_hovered: bool,
        under_mouse: str | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._mouse = mouse
        self._is_window_hovered = is_window_hovered
        self._under_mouse = (
            None if under_mouse is None else SimpleNamespace(name=under_mouse)
        )
        self.flags_asked = 0
        return self

    def get_mouse_pos(self) -> ImVec2:
        return ImVec2(*self._mouse)

    def is_window_hovered(self, flags: int) -> bool:
        self.flags_asked = flags
        return self._is_window_hovered

    def get_current_context(self) -> SimpleNamespace:
        return SimpleNamespace(hovered_window=self._under_mouse)


def _is_on(imgui: _Imgui) -> bool:
    return GlyphHit().is_on(imgui, _LOW, _HIGH)


def test_the_mouse_inside_the_rect_of_the_front_window_is_on_the_glyph() -> None:
    assert _is_on(_Imgui(_INSIDE, is_window_hovered=True))


def test_the_mouse_outside_the_rect_is_not_on_the_glyph() -> None:
    assert not _is_on(_Imgui(_OUTSIDE, is_window_hovered=True))


def test_a_rect_covered_by_another_window_is_not_hit() -> None:
    assert not _is_on(_Imgui(_INSIDE, is_window_hovered=False, under_mouse="Other##f2"))


def test_a_rect_with_no_window_under_the_mouse_is_not_hit() -> None:
    assert not _is_on(_Imgui(_INSIDE, is_window_hovered=False))


@pytest.mark.parametrize("popup", ["##Popup_1a2b", "##Popup_ffff"])
def test_a_rect_under_a_popup_is_still_hit(popup: str) -> None:
    assert _is_on(_Imgui(_INSIDE, is_window_hovered=False, under_mouse=popup))


def test_a_blocking_popup_or_active_title_bar_press_does_not_hide_the_window() -> None:
    imgui = _Imgui(_INSIDE, is_window_hovered=True)
    _is_on(imgui)
    assert imgui.flags_asked == 8 | 32
