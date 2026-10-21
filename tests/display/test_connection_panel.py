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


def test_the_close_button_follows_the_title_on_its_line_with_a_gap() -> None:
    """Placed after the title, not from leftover width: the popup auto-sizes to
    its contents, so a width-derived offset would feed back into itself."""
    imgui = FakeImGui()
    ConnectionPanel(_ROWS).render(imgui)
    offset, spacing = imgui.same_lines[0]
    assert (offset, spacing) == (0.0, 2 * imgui.get_style().item_spacing.x)


def test_the_header_layout_is_the_same_on_every_render() -> None:
    first, second = FakeImGui(), FakeImGui()
    panel = ConnectionPanel(_ROWS)
    panel.render(first)
    panel.render(second)
    assert first.same_lines == second.same_lines


def test_the_header_layout_does_not_depend_on_the_rows() -> None:
    short, long = FakeImGui(), FakeImGui()
    ConnectionPanel(()).render(short)
    ConnectionPanel(_ROWS).render(long)
    assert short.same_lines == long.same_lines
