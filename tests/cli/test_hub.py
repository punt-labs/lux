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


class TestHubStop:
    def test_stop_calls_the_service_manager(self) -> None:
        with patch("punt_lux.cli.hub.ServiceManager") as mock_cls:
            mock_cls.return_value.stop.return_value = "luxd stopped."
            result = runner.invoke(app, ["hub", "stop"])
        assert result.exit_code == 0
        assert "luxd stopped." in result.output
        mock_cls.return_value.stop.assert_called_once()


class TestHubInstall:
    def test_install_calls_the_service_manager(self) -> None:
        with patch("punt_lux.cli.hub.ServiceManager") as mock_cls:
            mock_cls.return_value.install.return_value = "luxd running on port 8430."
            result = runner.invoke(app, ["hub", "install"])
        assert result.exit_code == 0
        assert "luxd running on port 8430." in result.output
