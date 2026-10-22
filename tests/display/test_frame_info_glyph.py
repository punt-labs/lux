"""FrameInfoGlyph — a click is the release of a press that did not drag."""

from __future__ import annotations

from punt_lux.display.menus.frame_info_glyph import FrameInfoGlyph
from punt_lux.display.menus.glyph_canvas import GlyphCanvas
from punt_lux.display.menus.open_popup import OpenFrame
from punt_lux.display.menus.popup_cover import PopupCover
from punt_lux.domain.identity import HubId
from tests.display.test_frame_info_button import (
    _EXPECTED_ANCHOR,
    _OFF_BUTTON,
    _ON_BUTTON,
    _FakeImgui,
)

_FRAME = OpenFrame("f1", HubId.stub())
_NO_COVER = PopupCover(None, is_for_frame=False)


def _clicks(fake: _FakeImgui) -> list[tuple[float, float]]:
    reading = FrameInfoGlyph().render(GlyphCanvas(fake, _FRAME, _NO_COVER))
    return [reading.anchor] if reading.clicked else []


def _presses(fake: _FakeImgui) -> int:
    return int(FrameInfoGlyph().render(GlyphCanvas(fake, _FRAME, _NO_COVER)).pressed)


def test_a_release_on_the_glyph_reports_its_anchor() -> None:
    fake = _FakeImgui(expanded=True, clicked=True, mouse=_ON_BUTTON)
    assert _clicks(fake) == [_EXPECTED_ANCHOR]


def test_a_release_off_the_glyph_reports_nothing() -> None:
    fake = _FakeImgui(expanded=True, clicked=True, mouse=_OFF_BUTTON)
    assert _clicks(fake) == []


def test_a_hover_without_a_release_reports_nothing() -> None:
    fake = _FakeImgui(expanded=True, clicked=False, mouse=_ON_BUTTON)
    assert _clicks(fake) == []


def test_a_release_that_dragged_reports_nothing() -> None:
    fake = _FakeImgui(expanded=True, clicked=True, mouse=_ON_BUTTON, drag=(0.0, 9.0))
    assert _clicks(fake) == []


def test_a_wobble_inside_the_drag_threshold_is_still_a_click() -> None:
    fake = _FakeImgui(expanded=True, clicked=True, mouse=_ON_BUTTON, drag=(2.0, 2.0))
    assert _clicks(fake) == [_EXPECTED_ANCHOR]


def test_a_press_on_the_glyph_is_reported() -> None:
    fake = _FakeImgui(expanded=True, clicked=True, mouse=_ON_BUTTON)
    assert _presses(fake) == 1


def test_a_press_off_the_glyph_is_not_reported() -> None:
    fake = _FakeImgui(expanded=True, clicked=True, mouse=_OFF_BUTTON)
    assert _presses(fake) == 0
