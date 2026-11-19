"""Exercise extracted window defaults without starting a window or GL context."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from punt_lux.display.fonts import FontLoader
from punt_lux.display.setup import DisplaySetup


def test_runner_defaults_and_font_callback() -> None:
    params = DisplaySetup.parameters()
    assert params.app_window_params.window_title == "Lux"
    assert tuple(params.app_window_params.window_geometry.size) == (1200, 800)
    assert params.imgui_window_params.show_menu_bar
    assert not params.imgui_window_params.show_status_bar
    assert params.fps_idling.fps_idle == 30.0
    assert isinstance(params.callbacks.load_additional_fonts.__self__, FontLoader)


def test_addons_include_plots_and_markdown() -> None:
    addons = DisplaySetup.addons()
    assert addons.with_implot
    assert addons.with_markdown_options is not None or addons.with_markdown


def test_background_installs_dockspace_before_drawing_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeFlag:
        value = 7

    class FakeDockFlags:
        passthru_central_node = FakeFlag()

    class FakeImgui:
        DockNodeFlags_ = FakeDockFlags

        @staticmethod
        def dock_space_over_viewport(*, flags: int) -> None:
            assert flags == 7
            events.append("dock")

    def render_idle(_imgui: object) -> None:
        events.append("idle")

    monkeypatch.setattr("punt_lux.display.setup.render_idle", render_idle)
    DisplaySetup.background(FakeImgui)
    assert events == ["dock", "idle"]
