"""CLI-adapter tests for ``lux display`` -- the fused theme/mode/window verbs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.operations import (
    DisplayInfo,
    DisplayModeState,
    ThemeState,
    WindowSettings,
)

runner = CliRunner()


class _DisplayClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_display_info(self) -> DisplayInfo:
        return DisplayInfo(
            backend="opengl3",
            window_width=800,
            window_height=600,
            fps=60.0,
            pid=1,
            uptime_seconds=1.0,
            protocol_version="1",
            element_kinds=25,
        )

    def get_theme(self) -> ThemeState:
        self.calls.append(("get_theme", None))
        return ThemeState(theme="imgui_colors_dark", available=["imgui_colors_dark"])

    def set_theme(self, request: object) -> ThemeState:
        self.calls.append(("set_theme", request))
        return ThemeState(theme="darcula", available=["darcula"])

    def get_window_settings(self) -> WindowSettings:
        self.calls.append(("get_window_settings", None))
        return WindowSettings(opacity=1.0, font_scale=1.0, decorated=True, fps_idle=5.0)

    def set_window_settings(self, patch: object) -> WindowSettings:
        self.calls.append(("set_window_settings", patch))
        return WindowSettings(opacity=0.5, font_scale=1.0, decorated=True, fps_idle=5.0)

    def read_display_mode(self, repo: str) -> DisplayModeState:
        self.calls.append(("read_display_mode", repo))
        return DisplayModeState(mode="on")

    def write_display_mode(self, request: object) -> DisplayModeState:
        self.calls.append(("write_display_mode", request))
        return DisplayModeState(mode="off")


class TestDisplayInfo:
    def test_info_reads_display_metadata(self) -> None:
        client = _DisplayClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["display", "info"])
        assert result.exit_code == 0


class TestDisplayThemeFused:
    def test_no_argument_reads_the_theme(self) -> None:
        client = _DisplayClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["display", "theme"])
        assert result.exit_code == 0
        assert client.calls == [("get_theme", None)]

    def test_an_argument_sets_the_theme(self) -> None:
        client = _DisplayClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["display", "theme", "darcula"])
        assert result.exit_code == 0
        assert client.calls[0][0] == "set_theme"

    def test_an_invalid_theme_name_is_rejected_before_any_network_call(self) -> None:
        client = _DisplayClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["display", "theme", "not-a-real-theme"])
        assert result.exit_code == 1
        assert client.calls == []


class TestDisplayWindowFused:
    def test_no_options_reads_window_settings(self) -> None:
        client = _DisplayClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["display", "window"])
        assert result.exit_code == 0
        assert client.calls == [("get_window_settings", None)]

    def test_an_option_sets_window_settings(self) -> None:
        client = _DisplayClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["display", "window", "--opacity", "0.5"])
        assert result.exit_code == 0
        assert client.calls[0][0] == "set_window_settings"


class TestDisplayModeFused:
    def test_no_value_reads_the_mode(self) -> None:
        client = _DisplayClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["display", "mode", "--repo", "/tmp/proj"])
        assert result.exit_code == 0
        assert client.calls == [("read_display_mode", "/tmp/proj")]

    def test_a_value_sets_the_mode(self, tmp_path: Path) -> None:
        client = _DisplayClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(
                app, ["display", "mode", "off", "--repo", str(tmp_path)]
            )
        assert result.exit_code == 0
        assert client.calls[0][0] == "write_display_mode"

    def test_an_invalid_mode_value_is_rejected_before_any_network_call(
        self, tmp_path: Path
    ) -> None:
        client = _DisplayClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(
                app, ["display", "mode", "bogus", "--repo", str(tmp_path)]
            )
        assert result.exit_code == 2  # typer usage error, not a traceback
        assert client.calls == []

    def test_a_nonexistent_repo_reports_the_shared_error_envelope_not_a_crash(
        self,
    ) -> None:
        """Regression: OpError from DisplayModeRequest.parse used to crash the
        CLI with an unhandled ValidationError (Bugbot MEDIUM 2) -- confirms it
        is now caught client-side and reported as the shared error envelope,
        exiting cleanly rather than with a traceback."""
        client = _DisplayClient()
        with patch(
            "punt_lux.rest_client.LuxRestClient.for_identity", return_value=client
        ):
            result = runner.invoke(
                app,
                ["display", "mode", "on", "--repo", "/nonexistent/path/xyz"],
            )
        assert result.exit_code == 1
        assert "does not exist" in result.output
        assert client.calls == []


class TestDisplayAdminVerbs:
    def test_install_delegates_to_display_service_manager(self) -> None:
        with patch("punt_lux.cli.display_service.ServiceManager") as mock_cls:
            mock_cls.for_display.return_value.install.return_value = (
                "luxd-display installed."
            )
            result = runner.invoke(app, ["display", "install"])
        assert result.exit_code == 0
        assert "luxd-display installed." in result.output
        mock_cls.for_display.assert_called_once()

    def test_start_reports_not_installed(self) -> None:
        from punt_lux.service import ServiceNotInstalledError

        with patch("punt_lux.cli.display_service.ServiceManager") as mock_cls:
            mock_cls.for_display.return_value.start.side_effect = (
                ServiceNotInstalledError(
                    "luxd-display is not installed. Run 'lux display install' first."
                )
            )
            result = runner.invoke(app, ["display", "start"])
        assert result.exit_code == 1
        assert "lux display install" in result.output

    def test_stop_delegates(self) -> None:
        with patch("punt_lux.cli.display_service.ServiceManager") as mock_cls:
            mock_cls.for_display.return_value.stop.return_value = (
                "luxd-display stopped."
            )
            result = runner.invoke(app, ["display", "stop"])
        assert result.exit_code == 0
        assert "luxd-display stopped." in result.output
