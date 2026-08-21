"""Unit tests for punt_lux.display_restart — DisplayRestart.

``_term`` and ``_live_pid`` must resolve the pid to signal via the socket's
live peer credential (``DisplayPaths.peer_pid``), never the pid file: a pid
file can be stale or reused by an unrelated process, and signalling on that
faith is not safe.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from punt_lux.display_restart import DisplayRestart, DisplayRestartError


def _paths(*, peer_pid: int | None, is_running: bool = True) -> MagicMock:
    paths = MagicMock()
    paths.peer_pid.return_value = peer_pid
    paths.is_running.return_value = is_running
    paths.socket_path = "/tmp/lux-test/display.sock"
    return paths


class TestTerm:
    def test_signals_the_peer_credential_pid_not_the_pid_file(self) -> None:
        paths = _paths(peer_pid=4242)
        restart = DisplayRestart(paths)
        killed: list[tuple[int, int]] = []

        def _record(pid: int, sig: int) -> None:
            killed.append((pid, sig))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("punt_lux.display_restart.os.kill", _record)
            pid = restart._term()
        assert pid == 4242
        assert killed == [(4242, 15)]  # SIGTERM
        paths.pid_path.read_text.assert_not_called()

    def test_raises_when_the_peer_credential_cannot_be_resolved(self) -> None:
        paths = _paths(peer_pid=None)
        restart = DisplayRestart(paths)
        with pytest.raises(DisplayRestartError, match="could not resolve"):
            restart._term()

    def test_raises_when_the_signal_itself_fails(self) -> None:
        paths = _paths(peer_pid=4242)
        restart = DisplayRestart(paths)
        with pytest.MonkeyPatch.context() as mp:

            def _raise(pid: int, sig: int) -> None:
                raise ProcessLookupError

            mp.setattr("punt_lux.display_restart.os.kill", _raise)
            with pytest.raises(DisplayRestartError, match="could not signal display"):
                restart._term()


class TestLivePid:
    def test_returns_none_while_the_socket_is_not_running(self) -> None:
        paths = _paths(peer_pid=99, is_running=False)
        restart = DisplayRestart(paths)
        assert restart._live_pid() is None
        paths.peer_pid.assert_not_called()

    def test_resolves_the_running_socket_via_peer_credential(self) -> None:
        paths = _paths(peer_pid=99, is_running=True)
        restart = DisplayRestart(paths)
        assert restart._live_pid() == 99
