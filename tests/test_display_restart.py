"""Tests for DisplayRestart — restart via the supervisor, wait for pid change."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.display_restart import DisplayRestart, DisplayRestartError
from punt_lux.service import ServiceActionFailedError, ServiceNotInstalledError


def _pid_series(*values: int | None) -> Iterator[int | None]:
    return iter(values)


def _fake_pgrep(series: Iterator[int | None]) -> object:
    def _next(_name: str) -> int | None:
        return next(series)

    return _next


class TestDisplayRestartSuccess:
    def test_succeeds_when_pid_changes(self) -> None:
        manager = MagicMock()
        manager.restart.return_value = "display restarted."
        series = _pid_series(500, 501)

        with (
            patch("punt_lux.display_restart._POLL_SECONDS", 0.001),
            patch(
                "punt_lux.display_restart.pgrep_pid", side_effect=_fake_pgrep(series)
            ),
        ):
            result = DisplayRestart(manager=manager).run()

        assert "pid 501" in result

    def test_succeeds_on_fresh_install_none_to_pid(self) -> None:
        """On a first-ever install, the display is not up when the supervisor
        call goes out — install.sh runs this the moment 'display install'
        returns. The moment a pid appears is the restart, and the wait must
        accept it without demanding a prior pid."""
        manager = MagicMock()
        manager.restart.return_value = "display restarted."
        series = _pid_series(None, 77)

        with (
            patch("punt_lux.display_restart._POLL_SECONDS", 0.001),
            patch(
                "punt_lux.display_restart.pgrep_pid", side_effect=_fake_pgrep(series)
            ),
        ):
            result = DisplayRestart(manager=manager).run()

        assert "pid 77" in result

    def test_ignores_old_pid_still_exiting(self) -> None:
        manager = MagicMock()
        manager.restart.return_value = "display restarted."
        series = _pid_series(500, 500, 501)

        with (
            patch("punt_lux.display_restart._POLL_SECONDS", 0.001),
            patch(
                "punt_lux.display_restart.pgrep_pid", side_effect=_fake_pgrep(series)
            ),
        ):
            result = DisplayRestart(manager=manager).run()

        assert "pid 501" in result


class TestDisplayRestartFailure:
    def test_raises_when_supervisor_call_fails(self) -> None:
        manager = MagicMock()
        manager.restart.side_effect = ServiceActionFailedError(
            "display restart failed. See ~/.punt-labs/lux/logs/ for details."
        )
        with pytest.raises(DisplayRestartError, match="restart failed"):
            DisplayRestart(manager=manager).run()

    def test_raises_when_service_not_installed(self) -> None:
        manager = MagicMock()
        manager.restart.side_effect = ServiceNotInstalledError(
            "display is not installed. Run 'lux display install' first."
        )
        with pytest.raises(DisplayRestartError, match="lux display install"):
            DisplayRestart(manager=manager).run()

    def test_raises_when_pid_never_changes(self) -> None:
        manager = MagicMock()
        manager.restart.return_value = "display restarted."
        with (
            patch("punt_lux.display_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.display_restart._WAIT_SECONDS", 0.01),
            patch("punt_lux.display_restart.pgrep_pid", return_value=500),
            pytest.raises(DisplayRestartError, match="did not come back"),
        ):
            DisplayRestart(manager=manager).run()
