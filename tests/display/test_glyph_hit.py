"""GlyphHit — the mouse counts on a glyph only while nothing covers its window."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Self, final

from imgui_bundle import ImVec2

from punt_lux.display.menus.glyph_canvas import GlyphCanvas
from punt_lux.display.menus.glyph_hit import GlyphHit
from punt_lux.display.menus.open_popup import OpenFrame
from punt_lux.display.menus.popup_cover import PopupCover
from punt_lux.domain.identity import HubId

_FRAME = OpenFrame("f1", HubId.stub())
_LOW = ImVec2(10.0, 10.0)
_HIGH = ImVec2(20.0, 20.0)
_INSIDE = (15.0, 15.0)
_OUTSIDE = (50.0, 50.0)
_BLOCKED_BY_POPUP = 8
_BLOCKED_BY_ACTIVE_ITEM = 32
_INFO_POPUP = 0x438CCE0B
_OTHER_POPUP = 0x1234ABCD
_NO_COVER = PopupCover(None, is_for_frame=False)
_OWN_COVER = PopupCover(_INFO_POPUP, is_for_frame=True)
_ELSEWHERE_COVER = PopupCover(_INFO_POPUP, is_for_frame=False)


def _window(popup_id: int = 0) -> SimpleNamespace:
    """A scripted ImGui window; ``popup_id`` is 0 for a window that is no popup."""
    return SimpleNamespace(
        popup_id=popup_id, root_window=SimpleNamespace(popup_id=popup_id)
    )


@final
class _Imgui:
    """Scripts the mouse, this window's hover, the hovered and the focused window."""

    HoveredFlags_ = SimpleNamespace(
        allow_when_blocked_by_popup=SimpleNamespace(value=_BLOCKED_BY_POPUP),
        allow_when_blocked_by_active_item=SimpleNamespace(
            value=_BLOCKED_BY_ACTIVE_ITEM
        ),
    )

    _mouse: tuple[float, float]
    _is_window_hovered: bool
    _under_mouse: SimpleNamespace | None
    _focused: SimpleNamespace | None
    flags_asked: int
    __slots__ = (
        "_focused",
        "_is_window_hovered",
        "_mouse",
        "_under_mouse",
        "flags_asked",
    )

    def __new__(
        cls,
        mouse: tuple[float, float],
        *,
        is_window_hovered: bool,
        under_mouse: SimpleNamespace | None = None,
        focused: SimpleNamespace | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._mouse = mouse
        self._is_window_hovered = is_window_hovered
        self._under_mouse = under_mouse
        self._focused = focused
        self.flags_asked = 0
        return self

    def get_mouse_pos(self) -> ImVec2:
        return ImVec2(*self._mouse)

    def is_window_hovered(self, flags: int) -> bool:
        self.flags_asked = flags
        return self._is_window_hovered

    def get_current_context(self) -> SimpleNamespace:
        return SimpleNamespace(
            hovered_window=self._under_mouse, nav_window=self._focused
        )


def _is_on(imgui: _Imgui, popup: PopupCover = _NO_COVER) -> bool:
    return GlyphHit().is_on(GlyphCanvas(imgui, _FRAME, popup), _LOW, _HIGH)


def test_the_mouse_inside_the_rect_of_the_front_window_is_on_the_glyph() -> None:
    assert _is_on(_Imgui(_INSIDE, is_window_hovered=True))


def test_the_mouse_outside_the_rect_is_not_on_the_glyph() -> None:
    assert not _is_on(_Imgui(_OUTSIDE, is_window_hovered=True))


def test_a_rect_covered_by_another_window_is_not_hit() -> None:
    assert not _is_on(_Imgui(_INSIDE, is_window_hovered=False, under_mouse=_window()))


def test_a_rect_with_no_window_under_the_mouse_is_not_hit() -> None:
    assert not _is_on(_Imgui(_INSIDE, is_window_hovered=False))


def test_a_rect_under_its_own_frames_info_popup_is_still_hit() -> None:
    imgui = _Imgui(
        _INSIDE,
        is_window_hovered=False,
        under_mouse=_window(_INFO_POPUP),
        focused=_window(_INFO_POPUP),
    )

    assert _is_on(imgui, _OWN_COVER)


def test_a_rect_under_the_info_popup_of_another_frame_is_not_hit() -> None:
    imgui = _Imgui(
        _INSIDE,
        is_window_hovered=False,
        under_mouse=_window(_INFO_POPUP),
        focused=_window(_INFO_POPUP),
    )

    assert not _is_on(imgui, _ELSEWHERE_COVER)


def test_a_rect_under_an_unrelated_popup_is_not_hit() -> None:
    imgui = _Imgui(
        _INSIDE,
        is_window_hovered=False,
        under_mouse=_window(_OTHER_POPUP),
        focused=_window(_OTHER_POPUP),
    )

    assert not _is_on(imgui, _OWN_COVER)


def test_an_unrelated_popup_holding_focus_does_not_get_looked_through() -> None:
    imgui = _Imgui(_INSIDE, is_window_hovered=True, focused=_window(_OTHER_POPUP))
    _is_on(imgui, _OWN_COVER)

    assert imgui.flags_asked == _BLOCKED_BY_ACTIVE_ITEM


def test_the_focused_info_popup_is_looked_through_for_any_frames_glyph() -> None:
    imgui = _Imgui(_INSIDE, is_window_hovered=True, focused=_window(_INFO_POPUP))
    _is_on(imgui, _ELSEWHERE_COVER)

    assert imgui.flags_asked == _BLOCKED_BY_POPUP | _BLOCKED_BY_ACTIVE_ITEM


def test_an_active_title_bar_press_does_not_hide_the_window() -> None:
    imgui = _Imgui(_INSIDE, is_window_hovered=True)
    _is_on(imgui)

    assert imgui.flags_asked == _BLOCKED_BY_ACTIVE_ITEM
