"""WindowSettings -- each preference is held beside the call that makes it true."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from imgui_bundle import hello_imgui

from punt_lux.display.window_settings import WindowSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def window(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """A live window that records what is done to it."""
    glfw = MagicMock()
    monkeypatch.setattr(WindowSettings, "_glfw_window", staticmethod(lambda: glfw))
    yield glfw


class TestDefaults:
    def test_a_new_window_is_decorated_opaque_and_dark(self) -> None:
        settings = WindowSettings()

        assert settings.decorated is True
        assert settings.opacity == 1.0
        assert settings.font_scale == 1.1
        assert settings.current_theme == "imgui_colors_dark"
        assert settings.themes == []


class TestEachSettingReachesTheWindow:
    def test_decoration_is_held_and_applied(self, window: MagicMock) -> None:
        settings = WindowSettings()

        settings.set_decorated(decorated=False)

        assert settings.decorated is False
        window.set_decorated.assert_called_once_with(decorated=False)

    def test_opacity_is_held_and_applied(self, window: MagicMock) -> None:
        settings = WindowSettings()

        settings.set_opacity(0.5)

        assert settings.opacity == 0.5
        window.set_opacity.assert_called_once_with(opacity=0.5)

    def test_font_scale_is_held_without_touching_the_window(
        self, window: MagicMock
    ) -> None:
        settings = WindowSettings()

        settings.set_font_scale(1.5)

        assert settings.font_scale == 1.5
        window.assert_not_called()


class TestThemes:
    def test_starting_learns_the_themes_and_stops_later_reshows_stealing_focus(
        self, window: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        light = SimpleNamespace(name="imgui_colors_light")
        monkeypatch.setattr(hello_imgui, "ImGuiTheme_", [light])
        settings = WindowSettings()

        settings.start()

        assert settings.themes == [light]
        window.set_focus_on_show.assert_called_once_with(focus=False)

    def test_a_known_theme_is_applied_and_remembered(
        self, window: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        light = SimpleNamespace(name="imgui_colors_light")
        applied: list[object] = []
        monkeypatch.setattr(hello_imgui, "ImGuiTheme_", [light])
        monkeypatch.setattr(hello_imgui, "apply_theme", applied.append)
        settings = WindowSettings()
        settings.start()

        settings.apply_theme("imgui_colors_light")

        assert applied == [light]
        assert settings.current_theme == "imgui_colors_light"

    def test_an_unknown_theme_changes_nothing_and_is_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        settings = WindowSettings()

        with caplog.at_level("WARNING"):
            settings.apply_theme("imgui_colors_nonesuch")

        assert settings.current_theme == "imgui_colors_dark"
        assert "Unknown theme" in caplog.text


class TestReports:
    def test_the_theme_report_names_the_current_theme_and_the_switchable_ones(
        self, window: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        light = SimpleNamespace(name="imgui_colors_light")
        count = SimpleNamespace(name="count")  # the sentinel, excluded
        monkeypatch.setattr(hello_imgui, "ImGuiTheme_", [light, count])
        settings = WindowSettings()
        settings.start()

        assert settings.theme_report() == {
            "current": "imgui_colors_dark",
            "available": ["imgui_colors_light"],
        }

    def test_the_window_report_carries_every_setting_and_the_idle_rate(
        self, window: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = SimpleNamespace(fps_idling=SimpleNamespace(fps_idle=9.0))
        monkeypatch.setattr(hello_imgui, "get_runner_params", lambda: runner)
        settings = WindowSettings()
        settings.set_opacity(0.5)

        assert settings.window_report() == {
            "opacity": 0.5,
            "font_scale": 1.1,
            "decorated": True,
            "fps_idle": 9.0,
        }
