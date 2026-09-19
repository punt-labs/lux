"""FrameInfoPopup — the title-bar glyph's popup, opened by open_for().

Modeled on WorldPanel: one popup at a time, placed at the anchor on first
render, dismissed on a click elsewhere, auto-closed if its frame disappears.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.display.menus.frame_info_popup import FrameInfoPopup
from punt_lux.display.replica.frame_visibility import FrameVisibility
from tests.menu_doubles import FakeImGui, make_frame

if TYPE_CHECKING:
    from punt_lux.display.replica.frame import Frame

_ROWS = (("Client", "lux"), ("Kind", "agent"))


def _frames(*ids: str) -> dict[str, Frame]:
    return {fid: make_frame(fid, visibility=FrameVisibility.ON_SCREEN) for fid in ids}


class TestOpening:
    def test_a_fresh_popup_is_closed(self) -> None:
        assert not FrameInfoPopup(lambda: _frames()).is_open

    def test_open_for_opens_the_popup(self) -> None:
        popup = FrameInfoPopup(lambda: _frames("f1"))
        popup.open_for("f1", _ROWS, (10.0, 20.0))
        assert popup.is_open

    def test_a_closed_popup_renders_nothing(self) -> None:
        popup = FrameInfoPopup(lambda: _frames("f1"))
        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.windows == ()

    def test_an_open_popup_renders_its_window(self) -> None:
        popup = FrameInfoPopup(lambda: _frames("f1"))
        popup.open_for("f1", _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.windows == ("Connection",)

    def test_an_open_popup_renders_its_rows_verbatim(self) -> None:
        popup = FrameInfoPopup(lambda: _frames("f1"))
        popup.open_for("f1", _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.table_rows == _ROWS


class TestOneAtATime:
    def test_opening_a_second_frame_replaces_the_first(self) -> None:
        popup = FrameInfoPopup(lambda: _frames("f1", "f2"))
        popup.open_for("f1", _ROWS, (10.0, 20.0))

        popup.open_for("f2", (("Client", "quarry"),), (30.0, 40.0))

        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.table_rows == (("Client", "quarry"),)

    def test_only_one_window_is_ever_open(self) -> None:
        popup = FrameInfoPopup(lambda: _frames("f1", "f2"))
        popup.open_for("f1", _ROWS, (10.0, 20.0))
        popup.open_for("f2", _ROWS, (30.0, 40.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.windows == ("Connection",)


class TestDismissal:
    def test_the_close_button_shuts_the_popup(self) -> None:
        popup = FrameInfoPopup(lambda: _frames("f1"))
        popup.open_for("f1", _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        imgui.click_close_button()
        popup.render(imgui)
        assert not popup.is_open

    def test_a_background_click_dismisses_the_open_popup(self) -> None:
        popup = FrameInfoPopup(lambda: _frames("f1"))
        popup.open_for("f1", _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        imgui.click_background()
        popup.check_background_click(imgui)
        assert not popup.is_open

    def test_a_background_click_on_a_shut_popup_is_a_no_op(self) -> None:
        popup = FrameInfoPopup(lambda: _frames("f1"))
        imgui = FakeImGui()
        imgui.click_background()
        popup.check_background_click(imgui)  # never raises; nothing to close
        assert not popup.is_open

    def test_a_click_on_a_widget_leaves_the_popup_open(self) -> None:
        popup = FrameInfoPopup(lambda: _frames("f1"))
        popup.open_for("f1", _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        imgui.click_widget()
        popup.check_background_click(imgui)
        assert popup.is_open


class TestAutoClose:
    def test_the_popup_closes_when_its_frame_is_gone(self) -> None:
        popup = FrameInfoPopup(lambda: _frames())  # the frame has since closed
        popup.open_for("f1", _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert not popup.is_open
        assert imgui.windows == ()

    def test_the_popup_stays_open_while_its_frame_still_exists(self) -> None:
        popup = FrameInfoPopup(lambda: _frames("f1"))
        popup.open_for("f1", _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert popup.is_open
