"""ConnectionPanel — the frame-info popup body: a header over the fact rows."""

from __future__ import annotations

from punt_lux.display.menus.connection_panel import ConnectionPanel
from tests.menu_doubles import FakeImGui

_ROWS = (("Client", "lux"), ("Kind", "agent"))


def test_the_panel_draws_its_rows_verbatim() -> None:
    imgui = FakeImGui()
    ConnectionPanel(_ROWS).render(imgui)
    assert imgui.table_rows == _ROWS


def test_an_empty_panel_draws_no_rows() -> None:
    imgui = FakeImGui()
    ConnectionPanel(()).render(imgui)
    assert imgui.table_rows == ()


def test_the_panel_reports_a_pressed_close_button() -> None:
    assert ConnectionPanel(_ROWS).render(FakeImGui(clicks={"x"}))


def test_the_panel_reports_no_close_when_nothing_was_pressed() -> None:
    assert not ConnectionPanel(_ROWS).render(FakeImGui())


# The fake lays text out at 8 px a character from x=108: "Connection" ends at 188.
_TITLE_END = 108.0 + 8.0 * len("Connection")
# "x" in a button: one 8 px character plus 4 px of padding either side.
_BUTTON_WIDTH = 16.0
_ITEM_SPACING = 8.0


def test_the_close_button_is_flush_with_the_right_content_edge() -> None:
    imgui = FakeImGui(table_right=440.0)
    ConnectionPanel(_ROWS).render(imgui)
    assert imgui.button_pos("x").x == 440.0 - _BUTTON_WIDTH


def test_the_close_button_never_overlaps_a_title_wider_than_the_rows() -> None:
    imgui = FakeImGui(table_right=150.0)
    ConnectionPanel(_ROWS).render(imgui)
    assert imgui.button_pos("x").x == _TITLE_END + _ITEM_SPACING


def test_the_close_button_sits_on_the_titles_line() -> None:
    imgui = FakeImGui(table_right=440.0)
    ConnectionPanel(_ROWS).render(imgui)
    assert imgui.button_pos("x").y == 108.0


def test_the_header_layout_is_the_same_on_every_render() -> None:
    first, second = FakeImGui(table_right=300.0), FakeImGui(table_right=300.0)
    panel = ConnectionPanel(_ROWS)
    panel.render(first)
    panel.render(second)
    assert first.button_pos("x") == second.button_pos("x")
