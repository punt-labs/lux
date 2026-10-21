"""GlyphClick — edges count only over the glyph, and a click only if undragged."""

from __future__ import annotations

from punt_lux.display.menus.glyph_click import GlyphClick
from tests.display.test_frame_info_button import _FakeImgui

_ANCHOR = (1.0, 2.0)


def _read(fake: _FakeImgui, *, hovered: bool) -> tuple[bool, bool]:
    reading = GlyphClick.read(fake, _ANCHOR, hovered=hovered)
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
    reading = GlyphClick.read(
        _FakeImgui(expanded=True, clicked=False), _ANCHOR, hovered=True
    )
    assert reading.anchor == _ANCHOR
