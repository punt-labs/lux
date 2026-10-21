"""CornerCloseButton -- flush right, clear of the text that leads its line."""

from __future__ import annotations

from punt_lux.display.menus.corner_close_button import CornerCloseButton
from tests.menu_doubles import FakeImGui, Vec2

_ORIGIN = Vec2(108.0, 108.0)


def _draw(imgui: FakeImGui, lead: str = "Hi") -> bool:
    imgui.text(lead)
    return CornerCloseButton("x", lead, _ORIGIN).render(imgui)


def test_the_button_is_flush_with_the_widest_content_so_far() -> None:
    imgui = FakeImGui(table_right=300.0)
    imgui.begin_table("t", 1)
    imgui.end_table()
    _draw(imgui)
    assert imgui.button_pos("x").x == 300.0 - 16.0


def test_the_button_clears_a_lead_text_wider_than_the_content() -> None:
    imgui = FakeImGui()
    _draw(imgui, lead="A long leading title")
    assert imgui.button_pos("x").x == 108.0 + 8.0 * 20 + 8.0


def test_the_button_sits_on_the_origins_line() -> None:
    imgui = FakeImGui()
    _draw(imgui)
    assert imgui.button_pos("x").y == _ORIGIN.y


def test_the_button_reports_a_press() -> None:
    assert _draw(FakeImGui(clicks={"x"}))


def test_the_button_reports_no_press_when_untouched() -> None:
    assert not _draw(FakeImGui())
