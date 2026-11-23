"""Supervisor failures stay outside native owner; operator stop prevents restart."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

if TYPE_CHECKING:
    import pytest

from punt_lux.pty.menu_process import MenuProcess


def test_helper_failure_is_bounded_and_does_not_escape_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    spawn = Mock(side_effect=OSError("process limit"))
    monkeypatch.setattr("punt_lux.pty.menu_process.time.monotonic", lambda: now[0])
    monkeypatch.setattr("punt_lux.pty.menu_process.os.posix_spawn", spawn)
    helper = MenuProcess()
    helper.start()
    helper.poll()
    assert spawn.call_count == 1
    now[0] = 6
    helper.poll()
    assert spawn.call_count == 2
    helper.close()
    now[0] = 12
    helper.poll()
    assert spawn.call_count == 2


def test_helper_is_observed_without_blocking_or_restarting_while_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Mock()
    child.poll.return_value = False
    spawn = Mock(return_value=123)
    monkeypatch.setattr("punt_lux.pty.menu_process.os.posix_spawn", spawn)

    def held(_pid: int) -> Mock:
        return child

    monkeypatch.setattr("punt_lux.pty.menu_process.ChildLifetime", held)
    helper = MenuProcess()
    helper.start()
    helper.poll()
    assert spawn.call_count == 1
    assert "setsid" not in spawn.call_args.kwargs
    helper.close()
    child.stop.assert_called_once_with()
