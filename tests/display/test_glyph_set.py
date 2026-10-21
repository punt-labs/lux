"""GlyphSet — a frame with no title bar has no glyph to draw or click."""

from __future__ import annotations

import pytest

from punt_lux.display.menus.frame_info_glyph import FrameInfoGlyph
from punt_lux.display.menus.glyph_canvas import GlyphCanvas
from punt_lux.display.menus.glyph_set import AbsentGlyph, GlyphSet
from punt_lux.display.menus.open_popup import OpenFrame
from punt_lux.display.menus.popup_cover import PopupCover
from punt_lux.display.replica.frame import Frame
from punt_lux.domain.identity import HubId


def _frame(flags: dict[str, bool] | None) -> Frame:
    return Frame(
        hub=HubId.stub(),
        frame_id="f1",
        title="F",
        owner_fds=set(),
        scenes={},
        scene_order=[],
        flags=flags,
    )


@pytest.mark.parametrize(
    "flags", [None, {}, {"no_resize": True}, {"no_title_bar": False}]
)
def test_a_frame_with_a_title_bar_gets_the_disc(flags: dict[str, bool] | None) -> None:
    assert isinstance(GlyphSet().for_frame(_frame(flags)), FrameInfoGlyph)


def test_a_frame_flagged_no_title_bar_gets_no_glyph() -> None:
    assert isinstance(GlyphSet().for_frame(_frame({"no_title_bar": True})), AbsentGlyph)


def test_the_absent_glyph_reads_no_mouse_edge() -> None:
    reading = AbsentGlyph().render(
        GlyphCanvas(
            object(),
            OpenFrame("f1", HubId.stub()),
            PopupCover(None, is_for_frame=False),
        )
    )
    assert not (reading.pressed or reading.released or reading.clicked)
