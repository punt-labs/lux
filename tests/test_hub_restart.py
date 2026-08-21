"""Tests for HubRestart — restart via the supervisor, wait for pid + port."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.hub_restart import HubRestart, HubRestartError
from punt_lux.service import ServiceActionFailedError, ServiceNotInstalledError


def _pid_series(*values: int | None) -> Iterator[int | None]:
    return iter(values)


def _fake_pgrep(series: Iterator[int | None]) -> object:
    def _next(_name: str) -> int | None:
        return next(series)

    return _next


def _paths_stub(*, is_running: bool = True, port: int | None = 8430) -> MagicMock:
    paths = MagicMock()
    paths.is_running.return_value = is_running
    paths.read_port.return_value = port
    return paths


def _pid_after(before: int, after: int) -> object:
    """Return a ``pgrep_pid`` side_effect: ``before`` once, then ``after`` forever.

    Models "the process genuinely restarted" without asserting how many
    times the wait polls — the first call captures ``before``, and every
    poll after that observes the new pid.
    """
    calls = iter([before])

    def _next(_name: str) -> int:
        return next(calls, after)

    return _next


class TestHubRestartSuccess:
    def test_succeeds_when_pid_changes_and_port_is_up(self) -> None:
        manager = MagicMock()
        manager.restart.return_value = "luxd restarted."
        series = _pid_series(12345, 99999)

        with (
            patch("punt_lux.hub_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.hub_restart.pgrep_pid", side_effect=_fake_pgrep(series)),
        ):
            result = HubRestart(manager=manager, paths=_paths_stub()).run()

        assert "pid 99999" in result
        assert "port 8430" in result

    def test_succeeds_on_fresh_install_none_to_pid(self) -> None:
        """No process before → a pid appearing after AND the port coming up.

        On a first-ever install the process is not up when the supervisor
        call goes out. Both witnesses must fire: pgrep sees the new pid AND
        the pid file exists (which luxd only writes after uvicorn binds).
        """
        manager = MagicMock()
        manager.restart.return_value = "luxd restarted."
        series = _pid_series(None, 42)

        with (
            patch("punt_lux.hub_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.hub_restart.pgrep_pid", side_effect=_fake_pgrep(series)),
        ):
            result = HubRestart(manager=manager, paths=_paths_stub()).run()

        assert "pid 42" in result

    def test_waits_for_port_when_pid_is_up_but_port_is_not(self) -> None:
        """luxd sets its process title BEFORE uvicorn binds, so pgrep can
        see the new pid while ``curl :8430`` still refuses. The wait must
        require the pid file (written after bind), not just the pid."""
        manager = MagicMock()
        manager.restart.return_value = "luxd restarted."
        # First pgrep call captures ``before``; subsequent calls return the
        # new pid on every poll. is_running goes True only once uvicorn binds
        # and writes the pid file.
        pgrep_series = _pid_series(12345, 99999, 99999, 99999)
        running_calls = iter([False, False, True])

        paths = MagicMock()
        paths.is_running.side_effect = lambda: next(running_calls)
        paths.read_port.return_value = 8430

        with (
            patch("punt_lux.hub_restart._POLL_SECONDS", 0.001),
            patch(
                "punt_lux.hub_restart.pgrep_pid",
                side_effect=_fake_pgrep(pgrep_series),
            ),
        ):
            result = HubRestart(manager=manager, paths=paths).run()

        assert "pid 99999" in result
        assert "port 8430" in result

    def test_ignores_old_pid_still_exiting(self) -> None:
        """First poll sees the OLD pid still exiting; wait for a genuinely
        new one before checking the port."""
        manager = MagicMock()
        manager.restart.return_value = "luxd restarted."
        series = _pid_series(12345, 12345, 99999)

        with (
            patch("punt_lux.hub_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.hub_restart.pgrep_pid", side_effect=_fake_pgrep(series)),
        ):
            result = HubRestart(manager=manager, paths=_paths_stub()).run()

        assert "pid 99999" in result


class TestHubRestartFailure:
    def test_raises_when_supervisor_call_fails(self) -> None:
        manager = MagicMock()
        manager.restart.side_effect = ServiceActionFailedError(
            "luxd restart failed. See ~/.punt-labs/lux/logs/ for details."
        )
        with pytest.raises(HubRestartError, match="restart failed"):
            HubRestart(manager=manager, paths=_paths_stub()).run()

    def test_raises_when_service_not_installed(self) -> None:
        manager = MagicMock()
        manager.restart.side_effect = ServiceNotInstalledError(
            "luxd is not installed. Run 'lux hub install' first."
        )
        with pytest.raises(HubRestartError, match="lux hub install"):
            HubRestart(manager=manager, paths=_paths_stub()).run()

    def test_raises_when_pid_never_changes(self) -> None:
        manager = MagicMock()
        manager.restart.return_value = "luxd restarted."
        with (
            patch("punt_lux.hub_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.hub_restart._WAIT_SECONDS", 0.01),
            patch("punt_lux.hub_restart.pgrep_pid", return_value=12345),
            pytest.raises(HubRestartError, match="did not come back"),
        ):
            HubRestart(manager=manager, paths=_paths_stub()).run()

    def test_raises_when_port_never_comes_up(self) -> None:
        """The pid changes (the process genuinely restarted) but the port
        never binds — the wait must fail on liveness, not on "pid never
        changed". A constant pgrep_pid across the whole run (the earlier
        version of this test) makes ``pid == before`` true forever, so the
        timeout fires for the wrong reason and the liveness branch is never
        exercised."""
        manager = MagicMock()
        manager.restart.return_value = "luxd restarted."
        paths = MagicMock()
        paths.is_running.return_value = False  # bind never completes
        with (
            patch("punt_lux.hub_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.hub_restart._WAIT_SECONDS", 0.01),
            patch(
                "punt_lux.hub_restart.pgrep_pid", side_effect=_pid_after(12345, 99999)
            ),
            pytest.raises(HubRestartError, match="did not come back"),
        ):
            HubRestart(manager=manager, paths=paths).run()
