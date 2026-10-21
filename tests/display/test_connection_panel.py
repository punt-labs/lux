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
