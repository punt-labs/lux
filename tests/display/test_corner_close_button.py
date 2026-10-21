"""CornerCloseButton -- flush right, clear of the text that leads its line."""

from __future__ import annotations

from punt_lux.display.menus.corner_close_button import CornerCloseButton
from tests.menu_doubles import FakeImGui, Vec2

_ORIGIN = Vec2(108.0, 108.0)
_ID = "##close"
# The fake's font is 12 px in a 16 px line; the button is a font-sized square.
_SIZE = 12.0
_LINE = 16.0


def _draw(imgui: FakeImGui, lead: str = "Hi") -> bool:
    imgui.text(lead)
    return CornerCloseButton(lead, _ORIGIN).render(imgui)


def test_the_button_is_flush_with_the_widest_content_so_far() -> None:
    imgui = FakeImGui(table_right=300.0)
    imgui.begin_table("t", 1)
    imgui.end_table()
    _draw(imgui)
    assert imgui.close_button_pos(_ID).x == 300.0 - _SIZE


def test_the_button_clears_a_lead_text_wider_than_the_content() -> None:
    imgui = FakeImGui()
    _draw(imgui, lead="A long leading title")
    assert imgui.close_button_pos(_ID).x == 108.0 + 8.0 * 20 + 8.0


def test_the_button_is_centred_on_the_title_line() -> None:
    imgui = FakeImGui()
    _draw(imgui)
    centre = imgui.close_button_pos(_ID).y + _SIZE / 2
    assert centre == _ORIGIN.y + _LINE / 2


def test_the_button_reserves_its_square_so_the_window_grows_to_hold_it() -> None:
    imgui = FakeImGui()
    _draw(imgui, lead="A long leading title")
    window = imgui.internal.get_current_window_read()
    assert window.dc.cursor_max_pos.x == 108.0 + 8.0 * 20 + 8.0 + _SIZE


def test_the_button_reports_a_press() -> None:
    assert _draw(FakeImGui(clicks={_ID}))


def test_the_button_reports_no_press_when_untouched() -> None:
    assert not _draw(FakeImGui())
