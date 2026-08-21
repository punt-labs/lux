"""Tests for DisplayRestart — restart via the supervisor, wait for pid + socket."""

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


def _paths_stub(*, is_running: bool = True, peer_pid: int | None = None) -> MagicMock:
    paths = MagicMock()
    paths.is_running.return_value = is_running
    paths.peer_pid.return_value = peer_pid
    paths.socket_path = "/tmp/lux-test/display.sock"
    return paths


class TestDisplayRestartSuccess:
    def test_succeeds_when_pid_changes_and_socket_is_up(self) -> None:
        manager = MagicMock()
        manager.restart.return_value = "display restarted."
        series = _pid_series(500, 501)

        with (
            patch("punt_lux.display_restart._POLL_SECONDS", 0.001),
            patch(
                "punt_lux.display_restart.pgrep_pid", side_effect=_fake_pgrep(series)
            ),
        ):
            result = DisplayRestart(
                manager=manager, paths=_paths_stub(peer_pid=501)
            ).run()

        assert "pid 501" in result

    def test_succeeds_on_fresh_install_none_to_pid(self) -> None:
        """On a first-ever install the display is not up when the supervisor
        call goes out; the moment a pid appears AND the socket accepts is the
        restart."""
        manager = MagicMock()
        manager.restart.return_value = "display restarted."
        series = _pid_series(None, 77)

        with (
            patch("punt_lux.display_restart._POLL_SECONDS", 0.001),
            patch(
                "punt_lux.display_restart.pgrep_pid", side_effect=_fake_pgrep(series)
            ),
        ):
            result = DisplayRestart(
                manager=manager, paths=_paths_stub(peer_pid=77)
            ).run()

        assert "pid 77" in result

    def test_waits_for_socket_when_pid_is_up_but_socket_is_not(self) -> None:
        """setproctitle fires before the socket binds, so pgrep can see the
        new pid while the socket still refuses connects. The wait must
        require both."""
        manager = MagicMock()
        manager.restart.return_value = "display restarted."
        pgrep_series = _pid_series(500, 501, 501, 501)
        running_calls = iter([False, False, True])

        paths = MagicMock()
        paths.is_running.side_effect = lambda: next(running_calls)
        paths.peer_pid.return_value = 501
        paths.socket_path = "/tmp/lux-test/display.sock"

        with (
            patch("punt_lux.display_restart._POLL_SECONDS", 0.001),
            patch(
                "punt_lux.display_restart.pgrep_pid",
                side_effect=_fake_pgrep(pgrep_series),
            ),
        ):
            result = DisplayRestart(manager=manager, paths=paths).run()

        assert "pid 501" in result

    def test_waits_for_peer_pid_when_socket_answers_but_still_the_old_owner(
        self,
    ) -> None:
        """During kickstart, pgrep can see the new pid while the socket is
        still accepting on the OLD instance's lease — is_running() alone
        would witness the wrong owner. peer_pid() must also agree with the
        new pid before the restart is reported."""
        manager = MagicMock()
        manager.restart.return_value = "display restarted."
        pgrep_series = _pid_series(500, 501, 501, 501)
        # is_running() is true throughout (old owner still accepting, then
        # the new one); peer_pid() names the OLD pid until the lease moves.
        peer_pid_calls = iter([500, 500, 501])

        paths = MagicMock()
        paths.is_running.return_value = True
        paths.peer_pid.side_effect = lambda: next(peer_pid_calls)
        paths.socket_path = "/tmp/lux-test/display.sock"

        with (
            patch("punt_lux.display_restart._POLL_SECONDS", 0.001),
            patch(
                "punt_lux.display_restart.pgrep_pid",
                side_effect=_fake_pgrep(pgrep_series),
            ),
        ):
            result = DisplayRestart(manager=manager, paths=paths).run()

        assert "pid 501" in result

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
            result = DisplayRestart(
                manager=manager, paths=_paths_stub(peer_pid=501)
            ).run()

        assert "pid 501" in result


class TestDisplayRestartFailure:
    def test_raises_when_supervisor_call_fails(self) -> None:
        manager = MagicMock()
        manager.restart.side_effect = ServiceActionFailedError(
            "display restart failed. See ~/.punt-labs/lux/logs/ for details."
        )
        with pytest.raises(DisplayRestartError, match="restart failed"):
            DisplayRestart(manager=manager, paths=_paths_stub()).run()

    def test_raises_when_service_not_installed(self) -> None:
        manager = MagicMock()
        manager.restart.side_effect = ServiceNotInstalledError(
            "display is not installed. Run 'lux display install' first."
        )
        with pytest.raises(DisplayRestartError, match="lux display install"):
            DisplayRestart(manager=manager, paths=_paths_stub()).run()

    def test_raises_when_pid_never_changes(self) -> None:
        manager = MagicMock()
        manager.restart.return_value = "display restarted."
        with (
            patch("punt_lux.display_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.display_restart._WAIT_SECONDS", 0.01),
            patch("punt_lux.display_restart.pgrep_pid", return_value=500),
            pytest.raises(DisplayRestartError, match="did not come back"),
        ):
            DisplayRestart(manager=manager, paths=_paths_stub()).run()

    def test_raises_when_socket_never_comes_up(self) -> None:
        """The pid changes (genuine restart) but the socket never accepts —
        must fail on liveness, not on "pid never changed". A constant
        pgrep_pid (the earlier version of this test) makes ``pid == before``
        true forever, so the timeout fires for the wrong reason."""
        manager = MagicMock()
        manager.restart.return_value = "display restarted."
        paths = _paths_stub(is_running=False)
        with (
            patch("punt_lux.display_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.display_restart._WAIT_SECONDS", 0.01),
            patch(
                "punt_lux.display_restart.pgrep_pid",
                side_effect=_pid_after(500, 501),
            ),
            pytest.raises(DisplayRestartError, match="did not come back"),
        ):
            DisplayRestart(manager=manager, paths=paths).run()

    def test_raises_when_peer_pid_never_agrees(self) -> None:
        """The socket keeps accepting, but the kernel peer credential never
        names the new pid — the old owner never released the socket. Must
        fail rather than report a false restart."""
        manager = MagicMock()
        manager.restart.return_value = "display restarted."
        paths = _paths_stub(is_running=True, peer_pid=500)  # always the old pid
        with (
            patch("punt_lux.display_restart._POLL_SECONDS", 0.001),
            patch("punt_lux.display_restart._WAIT_SECONDS", 0.01),
            patch(
                "punt_lux.display_restart.pgrep_pid",
                side_effect=_pid_after(500, 501),
            ),
            pytest.raises(DisplayRestartError, match="did not come back"),
        ):
            DisplayRestart(manager=manager, paths=paths).run()
