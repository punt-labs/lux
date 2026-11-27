"""Typing exit in one terminal removes that terminal's window and nothing else."""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

pytest.importorskip("pyghostty")

from punt_lux.pty.daemon_exchange import DaemonExchange
from punt_lux.pty.menu_listener import TerminalMenu
from tests.pty.launchers import Launch
from tests.pty.stub_hub import StubHub

pytestmark = pytest.mark.integration


def _program(flag: Path) -> str:
    """A shell stand-in that exits once ``flag`` exists, as `exit` ends a shell."""
    wait = f"iter(lambda: os.path.exists({str(flag)!r}), True)"
    code = f"import os,time; [time.sleep(0.05) for _ in {wait}]"
    return f'{sys.executable} -c "{code}"'


async def _until(check: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 10
    while not check():
        assert time.monotonic() < deadline, "condition not reached"
        await asyncio.sleep(0.05)


def test_exit_in_one_of_three_terminals_leaves_exactly_two_scenes(
    daemon: Path, launch: Launch, tmp_path: Path
) -> None:
    flag = tmp_path / "exit-now"
    stays = [launch.session("sleep 60") for _ in range(2)]
    leaves = launch.session(_program(flag))
    hub = StubHub()
    menu = TerminalMenu(hub.clients, DaemonExchange(daemon))

    async def scenario() -> list[str]:
        task = asyncio.create_task(menu.serve())
        try:
            await _until(lambda: len(hub.scenes) == 3)
            flag.touch()
            await _until(lambda: len(hub.scenes) == 2)
            return sorted(hub.scenes)
        finally:
            task.cancel()

    remaining = asyncio.run(scenario())
    assert f"terminal-{leaves}" not in remaining
    assert remaining == sorted(f"terminal-{s}" for s in stays)
