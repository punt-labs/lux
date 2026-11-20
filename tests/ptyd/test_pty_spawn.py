"""The terminal child starts in the user's home, not luxd-pty's cwd."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from punt_lux.ptyd.pty_spawn import PtySpawn


def test_exec_chdirs_to_home_before_execvpe() -> None:
    """The child moves to HOME before exec, so the shell opens there, not at /."""
    env = {"HOME": "/Users/someone", "SHELL": "/bin/zsh", "PWD": "/opt/lux"}
    calls: list[str] = []

    def record_chdir(directory: str) -> None:
        calls.append(f"chdir:{directory}")

    def record_execvpe(*_args: object) -> None:
        calls.append("execvpe")

    with (
        patch("punt_lux.ptyd.pty_spawn.os.chdir", record_chdir),
        patch("punt_lux.ptyd.pty_spawn.os.execvpe", record_execvpe),
        patch("punt_lux.ptyd.pty_spawn.os._exit", side_effect=SystemExit),
        pytest.raises(SystemExit),
    ):
        PtySpawn._exec(["/bin/zsh", "-l"], env)
    assert calls == ["chdir:/Users/someone", "execvpe"]
    assert env["PWD"] == "/Users/someone"  # stale daemon PWD repaired


def test_exec_survives_unusable_home() -> None:
    """A missing or unusable HOME falls through to exec rather than failing."""
    env = {"HOME": "/nonexistent", "SHELL": "/bin/sh", "PWD": "/opt/lux"}
    calls: list[str] = []

    def failing_chdir(_dir: str) -> None:
        raise OSError("no such directory")

    def record_execvpe(*_args: object) -> None:
        calls.append("execvpe")

    with (
        patch("punt_lux.ptyd.pty_spawn.os.chdir", failing_chdir),
        patch("punt_lux.ptyd.pty_spawn.os.execvpe", record_execvpe),
        patch("punt_lux.ptyd.pty_spawn.os._exit", side_effect=SystemExit),
        pytest.raises(SystemExit),
    ):
        PtySpawn._exec(["/bin/sh", "-l"], env)
    assert calls == ["execvpe"]
    assert env["PWD"] == "/opt/lux"  # inherited PWD left intact when chdir fails


def test_exec_survives_missing_home_key() -> None:
    """An env with no HOME at all still reaches exec, never a dead child."""
    env = {"SHELL": "/bin/sh"}  # no HOME
    calls: list[str] = []

    def record_chdir(directory: str) -> None:
        calls.append(f"chdir:{directory}")

    def record_execvpe(*_args: object) -> None:
        calls.append("execvpe")

    with (
        patch("punt_lux.ptyd.pty_spawn.os.chdir", record_chdir),
        patch("punt_lux.ptyd.pty_spawn.os.execvpe", record_execvpe),
        patch("punt_lux.ptyd.pty_spawn.os._exit", side_effect=SystemExit),
        pytest.raises(SystemExit),
    ):
        PtySpawn._exec(["/bin/sh", "-l"], env)
    assert calls == ["execvpe"]  # no chdir attempted, exec still runs
