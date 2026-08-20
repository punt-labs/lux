"""CLI-adapter tests for ``lux hub`` -- the admin process-supervision group."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from punt_lux.__main__ import app

runner = CliRunner()


class TestHubStatus:
    def test_status_reports_not_running_with_no_pid_file(self) -> None:
        with patch("punt_lux.hub_paths.HubPaths.is_running", return_value=False):
            result = runner.invoke(app, ["hub", "status"])
        assert result.exit_code == 1
        assert "not running" in result.output


class TestHubStart:
    def test_start_resumes_a_stopped_installed_service(self) -> None:
        with (
            patch("punt_lux.hub_paths.HubPaths.is_running", return_value=False),
            patch("punt_lux.cli.hub.ServiceManager") as mock_cls,
        ):
            mock_cls.return_value.start.return_value = "luxd started."
            result = runner.invoke(app, ["hub", "start"])
        assert result.exit_code == 0
        assert "luxd started." in result.output
        mock_cls.return_value.start.assert_called_once()

    def test_start_reports_not_installed(self) -> None:
        from punt_lux.service import ServiceNotInstalledError

        with (
            patch("punt_lux.hub_paths.HubPaths.is_running", return_value=False),
            patch("punt_lux.cli.hub.ServiceManager") as mock_cls,
        ):
            mock_cls.return_value.start.side_effect = ServiceNotInstalledError(
                "luxd is not installed. Run 'lux hub install' first."
            )
            result = runner.invoke(app, ["hub", "start"])
        assert result.exit_code == 1
        assert "lux hub install" in result.output

    def test_start_reports_already_running_without_calling_the_backend(self) -> None:
        with (
            patch("punt_lux.hub_paths.HubPaths.is_running", return_value=True),
            patch("punt_lux.hub_paths.HubPaths.read_port", return_value=8430),
            patch("punt_lux.cli.hub.ServiceManager") as mock_cls,
        ):
            result = runner.invoke(app, ["hub", "start"])
        assert result.exit_code == 0
        assert "8430" in result.output
        mock_cls.return_value.start.assert_not_called()

    def test_start_reports_a_failed_supervisor_call_not_success(self) -> None:
        """Regression: the supervisor rejecting the start used to be silently
        reported as "luxd started." (Bugbot HIGH)."""
        from punt_lux.service import ServiceActionFailedError

        with (
            patch("punt_lux.hub_paths.HubPaths.is_running", return_value=False),
            patch("punt_lux.cli.hub.ServiceManager") as mock_cls,
        ):
            mock_cls.return_value.start.side_effect = ServiceActionFailedError(
                "luxd start failed. See ~/.punt-labs/lux/logs/luxd-stderr.log "
                "for details."
            )
            result = runner.invoke(app, ["hub", "start"])
        assert result.exit_code == 1
        assert "luxd start failed" in result.output
        assert "luxd started." not in result.output


class TestHubStop:
    def test_stop_calls_the_service_manager(self) -> None:
        with patch("punt_lux.cli.hub.ServiceManager") as mock_cls:
            mock_cls.return_value.stop.return_value = "luxd stopped."
            result = runner.invoke(app, ["hub", "stop"])
        assert result.exit_code == 0
        assert "luxd stopped." in result.output
        mock_cls.return_value.stop.assert_called_once()

    def test_stop_reports_a_failed_supervisor_call_not_success(self) -> None:
        """Regression: the supervisor rejecting the stop used to be silently
        reported as "luxd stopped." (Bugbot HIGH)."""
        from punt_lux.service import ServiceActionFailedError

        with patch("punt_lux.cli.hub.ServiceManager") as mock_cls:
            mock_cls.return_value.stop.side_effect = ServiceActionFailedError(
                "luxd stop failed. See ~/.punt-labs/lux/logs/luxd-stderr.log "
                "for details."
            )
            result = runner.invoke(app, ["hub", "stop"])
        assert result.exit_code == 1
        assert "luxd stop failed" in result.output
        assert "luxd stopped." not in result.output


class TestHubInstall:
    def test_install_calls_the_service_manager(self) -> None:
        with patch("punt_lux.cli.hub.ServiceManager") as mock_cls:
            mock_cls.return_value.install.return_value = "luxd running on port 8430."
            result = runner.invoke(app, ["hub", "install"])
        assert result.exit_code == 0
        assert "luxd running on port 8430." in result.output
