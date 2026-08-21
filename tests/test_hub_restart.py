"""Tests for HubRestart — restart via the supervisor, wait for pid change."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.hub_restart import HubRestart, HubRestartError
from punt_lux.service import ServiceActionFailedError, ServiceNotInstalledError


def _pid_series(*values: int | None) -> Iterator[int | None]:
    """Return an iterator yielding each pid the fake ``pgrep_pid`` should see."""
    return iter(values)


def _fake_pgrep(series: Iterator[int | None]) -> object:
    """Return a ``side_effect`` that yields from ``series`` per call."""

    def _next(_name: str) -> int | None:
        return next(series)

    return _next


class TestHubRestartSuccess:
    def test_succeeds_when_pid_changes(self) -> None:
        """Old pid → new pid is the canonical upgrade case."""
        manager = MagicMock()
        manager.restart.return_value = "luxd restarted."
        series = _pid_series(12345, 99999)

        with (
            patch("punt_lux.hub_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.hub_restart.pgrep_pid", side_effect=_fake_pgrep(series)),
        ):
            result = HubRestart(manager=manager).run()

        assert "pid 99999" in result

    def test_succeeds_on_fresh_install_none_to_pid(self) -> None:
        """No process running before → a pid appearing after is a restart.

        This is the F1 case: on a first-ever install the process is not up
        when the supervisor call goes out; the moment it appears is the
        restart, and the wait must accept it without demanding a prior pid.
        """
        manager = MagicMock()
        manager.restart.return_value = "luxd restarted."
        series = _pid_series(None, 42)

        with (
            patch("punt_lux.hub_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.hub_restart.pgrep_pid", side_effect=_fake_pgrep(series)),
        ):
            result = HubRestart(manager=manager).run()

        assert "pid 42" in result

    def test_ignores_old_pid_still_exiting(self) -> None:
        """First poll sees the OLD pid still exiting; wait for a genuinely new one.

        This is the F2 race: if the wait treats "any pid" as success, it
        returns while the previous instance has not yet reaped, and the
        caller believes a restart happened that has not.
        """
        manager = MagicMock()
        manager.restart.return_value = "luxd restarted."
        series = _pid_series(12345, 12345, 12345, 99999)

        with (
            patch("punt_lux.hub_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.hub_restart.pgrep_pid", side_effect=_fake_pgrep(series)),
        ):
            result = HubRestart(manager=manager).run()

        assert "pid 99999" in result


class TestHubRestartFailure:
    def test_raises_when_supervisor_call_fails(self) -> None:
        manager = MagicMock()
        manager.restart.side_effect = ServiceActionFailedError(
            "luxd restart failed. See ~/.punt-labs/lux/logs/ for details."
        )

        with pytest.raises(HubRestartError, match="restart failed"):
            HubRestart(manager=manager).run()

    def test_raises_when_service_not_installed(self) -> None:
        manager = MagicMock()
        manager.restart.side_effect = ServiceNotInstalledError(
            "luxd is not installed. Run 'lux hub install' first."
        )

        with pytest.raises(HubRestartError, match="lux hub install"):
            HubRestart(manager=manager).run()

    def test_raises_when_pid_never_changes(self) -> None:
        manager = MagicMock()
        manager.restart.return_value = "luxd restarted."

        with (
            patch("punt_lux.hub_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.hub_restart._WAIT_SECONDS", 0.01),
            patch("punt_lux.hub_restart.pgrep_pid", return_value=12345),
            pytest.raises(HubRestartError, match="did not come back"),
        ):
            HubRestart(manager=manager).run()
