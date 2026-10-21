"""PopupCover — which popup window may stand over a glyph without hiding it."""

from __future__ import annotations

from types import SimpleNamespace

from punt_lux.display.menus.popup_cover import PopupCover

_INFO = 0x438CCE0B
_OTHER = 0x1234ABCD


def _window(popup_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        popup_id=popup_id, root_window=SimpleNamespace(popup_id=popup_id)
    )


class _Imgui:
    def __init__(self, *, under: int | None = None, focused: int | None = None) -> None:
        self._under = None if under is None else _window(under)
        self._focused = None if focused is None else _window(focused)

    def get_current_context(self) -> SimpleNamespace:
        return SimpleNamespace(hovered_window=self._under, nav_window=self._focused)


def test_its_own_popup_under_the_mouse_for_its_own_frame_covers_the_glyph() -> None:
    assert PopupCover(_INFO, is_for_frame=True).is_under_mouse(_Imgui(under=_INFO))


def test_its_popup_under_the_mouse_for_another_frame_does_not() -> None:
    assert not PopupCover(_INFO, is_for_frame=False).is_under_mouse(_Imgui(under=_INFO))


def test_another_popup_under_the_mouse_does_not() -> None:
    assert not PopupCover(_INFO, is_for_frame=True).is_under_mouse(_Imgui(under=_OTHER))


def test_a_window_that_is_no_popup_does_not() -> None:
    assert not PopupCover(_INFO, is_for_frame=True).is_under_mouse(_Imgui(under=0))


def test_nothing_under_the_mouse_does_not() -> None:
    assert not PopupCover(_INFO, is_for_frame=True).is_under_mouse(_Imgui())


def test_an_unplaced_popup_covers_nothing_even_over_a_non_popup_window() -> None:
    assert not PopupCover(None, is_for_frame=True).is_under_mouse(_Imgui(under=0))


def test_the_info_popup_holding_focus_is_focused_for_any_frame() -> None:
    assert PopupCover(_INFO, is_for_frame=False).is_focused(_Imgui(focused=_INFO))


def test_another_popup_holding_focus_is_not_focused() -> None:
    assert not PopupCover(_INFO, is_for_frame=True).is_focused(_Imgui(focused=_OTHER))


def test_nothing_focused_is_not_focused() -> None:
    assert not PopupCover(_INFO, is_for_frame=True).is_focused(_Imgui())


def test_an_unplaced_popup_is_never_focused() -> None:
    assert not PopupCover(None, is_for_frame=True).is_focused(_Imgui(focused=0))
