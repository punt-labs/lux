"""Tests for HubRestart — restart via the service supervisor, wait for port."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.hub_paths import HubPaths
from punt_lux.hub_restart import HubRestart, HubRestartError
from punt_lux.service import ServiceActionFailedError, ServiceNotInstalledError


def _paths_at(root: Path) -> HubPaths:
    """Return a HubPaths rooted at ``root`` so tests never touch $HOME."""
    return HubPaths(root=root)


class TestHubRestartSuccess:
    def test_succeeds_without_pid_file_present(self, tmp_path: Path) -> None:
        """The broken pre-supervisor path read the pid file to signal luxd
        and errored with ENOENT when it was absent. Routing restart through
        the service manager removes that dependency; a run that never sees
        a hub.pid file must not fail."""
        paths = _paths_at(tmp_path)
        manager = MagicMock()
        manager.restart.return_value = "luxd restarted."

        assert not paths.pid_path.exists()

        with (
            patch("punt_lux.hub_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.hub_paths.HubPaths.is_running", return_value=True),
            patch("punt_lux.hub_paths.HubPaths.read_port", return_value=8430),
        ):
            result = HubRestart(paths=paths, manager=manager).run()

        manager.restart.assert_called_once()
        assert "luxd restarted" in result
        assert "port 8430" in result
        assert not paths.pid_path.exists()

    def test_reports_port_file_not_yet_written(self, tmp_path: Path) -> None:
        paths = _paths_at(tmp_path)
        manager = MagicMock()
        manager.restart.return_value = "luxd restarted."

        with (
            patch("punt_lux.hub_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.hub_paths.HubPaths.is_running", return_value=True),
            patch("punt_lux.hub_paths.HubPaths.read_port", return_value=None),
        ):
            result = HubRestart(paths=paths, manager=manager).run()

        assert "port file not yet written" in result


class TestHubRestartFailure:
    def test_raises_when_supervisor_call_fails(self, tmp_path: Path) -> None:
        paths = _paths_at(tmp_path)
        manager = MagicMock()
        manager.restart.side_effect = ServiceActionFailedError(
            "luxd restart failed. See ~/.punt-labs/lux/logs/ for details."
        )

        with pytest.raises(HubRestartError, match="restart failed"):
            HubRestart(paths=paths, manager=manager).run()

    def test_raises_when_service_not_installed(self, tmp_path: Path) -> None:
        paths = _paths_at(tmp_path)
        manager = MagicMock()
        manager.restart.side_effect = ServiceNotInstalledError(
            "luxd is not installed. Run 'lux hub install' first."
        )

        with pytest.raises(HubRestartError, match="lux hub install"):
            HubRestart(paths=paths, manager=manager).run()

    def test_raises_when_hub_does_not_come_back(self, tmp_path: Path) -> None:
        paths = _paths_at(tmp_path)
        manager = MagicMock()
        manager.restart.return_value = "luxd restarted."

        with (
            patch("punt_lux.hub_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.hub_restart._WAIT_SECONDS", 0.05),
            patch("punt_lux.hub_paths.HubPaths.is_running", return_value=False),
            pytest.raises(HubRestartError, match="did not come back"),
        ):
            HubRestart(paths=paths, manager=manager).run()
