"""GlyphCanvas — a frame glyph's ImGui handle, its frame, and the popup's stance."""

from __future__ import annotations

from punt_lux.display.menus.frame_info_popup import FrameInfoPopup
from punt_lux.display.menus.glyph_canvas import GlyphCanvas
from punt_lux.display.menus.open_popup import OpenFrame
from punt_lux.display.menus.popup_cover import PopupCover
from punt_lux.domain.identity import HubId
from tests.menu_doubles import FakeImGui, make_frame

_HUB = HubId.stub()
_ROWS = (("Client", "lux"),)
_F1 = OpenFrame("f1", _HUB)
_FRAMES = {"f1": make_frame("f1", hub=_HUB), "f2": make_frame("f2", hub=_HUB)}


def _popup() -> FrameInfoPopup:
    return FrameInfoPopup(lambda frame_id, _hub: _FRAMES.get(frame_id))


def test_a_closed_popup_covers_no_glyph() -> None:
    canvas = GlyphCanvas.over(object(), _popup(), _FRAMES["f1"])

    assert canvas.popup == PopupCover(None, is_for_frame=False)


def test_an_open_popup_is_for_its_own_frame_only() -> None:
    popup = _popup()
    popup.open_for(_F1, _ROWS, (0.0, 0.0))
    own = GlyphCanvas.over(object(), popup, _FRAMES["f1"]).popup
    other = GlyphCanvas.over(object(), popup, _FRAMES["f2"]).popup

    assert (own.is_for_frame, other.is_for_frame) == (True, False)


def test_a_placed_popup_hands_its_window_id_to_every_frames_canvas() -> None:
    popup = _popup()
    popup.open_for(_F1, _ROWS, (0.0, 0.0))
    imgui = FakeImGui()
    popup.render(imgui)
    other = GlyphCanvas.over(imgui, popup, _FRAMES["f2"])

    assert other.popup.window_id == popup.window_id


def test_the_canvas_names_the_frame_by_hub_and_id() -> None:
    canvas = GlyphCanvas.over(object(), _popup(), _FRAMES["f2"])

    assert canvas.frame == OpenFrame("f2", _HUB)


def test_the_canvas_carries_the_imgui_handle() -> None:
    imgui = object()

    assert GlyphCanvas.over(imgui, _popup(), _FRAMES["f1"]).imgui is imgui
