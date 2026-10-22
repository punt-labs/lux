"""GlyphReading — edges count only over the glyph, and a click only if undragged."""

from __future__ import annotations

from punt_lux.display.menus.glyph_reading import GlyphReading
from tests.display.test_frame_info_button import _FakeImgui

_ANCHOR = (1.0, 2.0)


def _read(fake: _FakeImgui, *, hovered: bool) -> tuple[bool, bool]:
    reading = GlyphReading.read(fake, _ANCHOR, hovered=hovered)
    return reading.pressed, reading.clicked


def test_a_press_and_release_over_the_glyph_read_as_both_edges() -> None:
    assert _read(_FakeImgui(expanded=True, clicked=True), hovered=True) == (True, True)


def test_no_edge_counts_off_the_glyph() -> None:
    assert _read(_FakeImgui(expanded=True, clicked=True), hovered=False) == (
        False,
        False,
    )


def test_a_drag_keeps_the_press_but_not_the_click() -> None:
    fake = _FakeImgui(expanded=True, clicked=True, drag=(0.0, 9.0))
    assert _read(fake, hovered=True) == (True, False)


def test_the_reading_carries_the_anchor() -> None:
    reading = GlyphReading.read(
        _FakeImgui(expanded=True, clicked=False), _ANCHOR, hovered=True
    )
    assert reading.anchor == _ANCHOR


def test_a_release_is_reported_wherever_the_mouse_is() -> None:
    reading = GlyphReading.read(
        _FakeImgui(expanded=True, clicked=True), _ANCHOR, hovered=False
    )
    assert reading.released


def test_a_drag_released_over_the_glyph_still_reports_the_release() -> None:
    fake = _FakeImgui(expanded=True, clicked=True, drag=(0.0, 9.0))
    assert GlyphReading.read(fake, _ANCHOR, hovered=True).released


def test_no_release_edge_reads_as_not_released() -> None:
    reading = GlyphReading.read(
        _FakeImgui(expanded=True, clicked=False), _ANCHOR, hovered=True
    )
    assert not reading.released
