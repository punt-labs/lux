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

    @property
    def sync(self) -> _DisplayClient:
        return self

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

    def get_window_settings(self) -> WindowSettings:
        self.calls.append(("get_window_settings", None))
        return WindowSettings(opacity=1.0, font_scale=1.0, decorated=True, fps_idle=5.0)

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
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["display", "info"])
        assert result.exit_code == 0


class TestDisplayThemeReadOnly:
    """``lux display theme`` is a read -- setting is the user's own gesture at
    the Display's own Lux ▸ Settings menu, never a client op (DES-088)."""

    def test_no_argument_reads_the_theme(self) -> None:
        client = _DisplayClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["display", "theme"])
        assert result.exit_code == 0
        assert client.calls == [("get_theme", None)]

    def test_an_argument_is_rejected_before_any_network_call(self) -> None:
        # The verb takes no argument any more; typer's own usage error fires
        # before the client is ever touched.
        client = _DisplayClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["display", "theme", "darcula"])
        assert result.exit_code == 2
        assert client.calls == []


class TestDisplayWindowReadOnly:
    """``lux display window`` is a read -- setting is the user's own gesture at
    the Display's own Lux ▸ Settings menu, never a client op (DES-088)."""

    def test_no_options_reads_window_settings(self) -> None:
        client = _DisplayClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["display", "window"])
        assert result.exit_code == 0
        assert client.calls == [("get_window_settings", None)]

    def test_an_option_is_rejected_before_any_network_call(self) -> None:
        # The verb takes no options any more; typer's own usage error fires
        # before the client is ever touched.
        client = _DisplayClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["display", "window", "--opacity", "0.5"])
        assert result.exit_code == 2
        assert client.calls == []


class TestDisplayModeFused:
    def test_no_value_reads_the_mode(self) -> None:
        client = _DisplayClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(app, ["display", "mode", "--repo", "/tmp/proj"])
        assert result.exit_code == 0
        assert client.calls == [("read_display_mode", "/tmp/proj")]

    def test_a_value_sets_the_mode(self, tmp_path: Path) -> None:
        # Setting the mode moved out of the Hub entirely (DES-088): the CLI
        # writes DisplayModeStore directly and never touches the client.
        client = _DisplayClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
        ):
            result = runner.invoke(
                app, ["display", "mode", "off", "--repo", str(tmp_path)]
            )
        assert result.exit_code == 0
        assert result.output.strip() == "display:off"
        assert client.calls == []
        content = (tmp_path / ".punt-labs" / "lux.md").read_text()
        assert 'display: "n"' in content

    def test_an_invalid_mode_value_is_rejected_before_any_network_call(
        self, tmp_path: Path
    ) -> None:
        client = _DisplayClient()
        with patch(
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
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
            "punt_lux.client.facade.LuxClient.for_identity", return_value=client
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

        with (
            patch("punt_lux.paths.DisplayPaths.is_running", return_value=False),
            patch("punt_lux.cli.display_service.ServiceManager") as mock_cls,
        ):
            mock_cls.for_display.return_value.start.side_effect = (
                ServiceNotInstalledError(
                    "luxd-display is not installed. Run 'lux display install' first."
                )
            )
            result = runner.invoke(app, ["display", "start"])
        assert result.exit_code == 1
        assert "lux display install" in result.output

    def test_start_reports_already_running_without_calling_the_supervisor(
        self,
    ) -> None:
        with (
            patch("punt_lux.paths.DisplayPaths.is_running", return_value=True),
            patch("punt_lux.cli.display_service.ServiceManager") as mock_cls,
        ):
            result = runner.invoke(app, ["display", "start"])
        assert result.exit_code == 0
        assert "display running" in result.output
        mock_cls.for_display.return_value.start.assert_not_called()

    def test_restart_delegates_to_display_restart(self) -> None:
        with patch("punt_lux.cli.display_service.DisplayRestart") as mock_cls:
            mock_cls.return_value.run.return_value = (
                "display restarted (pid 4242) at /tmp/lux/display.sock"
            )
            result = runner.invoke(app, ["display", "restart"])
        assert result.exit_code == 0
        assert "display restarted" in result.output
        mock_cls.return_value.run.assert_called_once()

    def test_stop_delegates(self) -> None:
        with patch("punt_lux.cli.display_service.ServiceManager") as mock_cls:
            mock_cls.for_display.return_value.stop.return_value = (
                "luxd-display stopped."
            )
            result = runner.invoke(app, ["display", "stop"])
        assert result.exit_code == 0
        assert "luxd-display stopped." in result.output
