"""The keeper reconciles every connect and survives every failure (real daemon)."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

pytest.importorskip("pyghostty")

from punt_lux.pty.daemon_exchange import DaemonExchange
from punt_lux.pty.terminal_keeper import TerminalKeeper
from punt_lux.pty.terminal_windows import TerminalWindows
from tests.pty.launchers import Launch
from tests.pty.stub_hub import StubHub

pytestmark = pytest.mark.integration

SLEEP = f"{sys.executable} -c 'import time; time.sleep(60)'"


async def _until(check: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "condition not reached"
        await asyncio.sleep(0.05)


def _keeper(daemon: Path, hub: StubHub) -> TerminalKeeper:
    return TerminalKeeper(DaemonExchange(daemon), TerminalWindows(hub.clients))


def test_every_running_session_gets_a_window_at_connect(
    daemon: Path, launch: Launch
) -> None:
    ids = [launch.session(SLEEP) for _ in range(3)]
    hub = StubHub()

    async def scenario() -> None:
        task = asyncio.create_task(_keeper(daemon, hub).serve())
        try:
            await _until(lambda: len(hub.scenes) == 3)
        finally:
            task.cancel()

    asyncio.run(scenario())
    assert sorted(hub.scenes) == sorted(f"terminal-{i}" for i in ids)


def test_a_stranded_window_is_removed_and_a_missing_one_added(
    daemon: Path, launch: Launch
) -> None:
    from punt_lux.pty.listed_session import ListedSession
    from punt_lux.pty.terminal_scenes import TerminalScenes

    running = launch.session(SLEEP)
    hub = StubHub()

    async def scenario() -> None:
        ghost = TerminalScenes().for_session(
            ListedSession("t0.999", "ghost", "running")
        )
        await hub.show(ghost)
        task = asyncio.create_task(_keeper(daemon, hub).serve())
        try:
            await _until(lambda: list(hub.scenes) == [f"terminal-{running}"])
        finally:
            task.cancel()

    asyncio.run(scenario())


def test_a_hub_restart_brings_every_window_back(daemon: Path, launch: Launch) -> None:
    ids = [launch.session(SLEEP) for _ in range(2)]
    hub = StubHub()
    keeper = _keeper(daemon, hub)

    async def scenario() -> None:
        task = asyncio.create_task(keeper.serve())
        try:
            await _until(lambda: len(hub.scenes) == 2)
            hub.go_down()
            hub.come_up(lose_scenes=True)
            keeper.resync()
            await _until(lambda: len(hub.scenes) == 2)
        finally:
            task.cancel()

    asyncio.run(scenario())
    assert sorted(hub.scenes) == sorted(f"terminal-{i}" for i in ids)


def test_a_hub_that_is_down_never_ends_the_serve_task(
    daemon: Path, launch: Launch
) -> None:
    session = launch.session(SLEEP)
    hub = StubHub()
    hub.go_down()

    async def scenario() -> None:
        task = asyncio.create_task(_keeper(daemon, hub).serve())
        try:
            await asyncio.sleep(0.5)
            assert not task.done()
            hub.come_up()
            await _until(lambda: f"terminal-{session}" in hub.scenes, timeout=15)
            assert not task.done()
        finally:
            task.cancel()

    asyncio.run(scenario())


def test_a_refused_scene_is_logged_with_its_session_and_serving_continues(
    daemon: Path, launch: Launch, caplog: pytest.LogCaptureFixture
) -> None:
    session = launch.session(SLEEP)
    hub = StubHub()
    hub.refuse("no room")

    async def scenario() -> None:
        task = asyncio.create_task(_keeper(daemon, hub).serve())
        try:
            await asyncio.sleep(0.5)
            assert not task.done()
        finally:
            task.cancel()

    asyncio.run(scenario())
    assert any(session in r.getMessage() for r in caplog.records)


def test_a_hub_that_is_down_logs_no_error_records(
    daemon: Path, launch: Launch, caplog: pytest.LogCaptureFixture
) -> None:
    launch.session(SLEEP)
    hub = StubHub()
    hub.go_down()

    async def scenario() -> None:
        task = asyncio.create_task(_keeper(daemon, hub).serve())
        try:
            await asyncio.sleep(0.5)
        finally:
            task.cancel()

    caplog.set_level(logging.DEBUG)
    asyncio.run(scenario())
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


def test_a_missing_daemon_never_ends_the_serve_task(tmp_path: Path) -> None:
    hub = StubHub()

    async def scenario() -> None:
        task = asyncio.create_task(
            TerminalKeeper(
                DaemonExchange(Path(os.devnull) / "none"), TerminalWindows(hub.clients)
            ).serve()
        )
        try:
            await asyncio.sleep(0.3)
            assert not task.done()
        finally:
            task.cancel()

    asyncio.run(scenario())


def test_n_clicks_end_as_n_distinct_scenes_and_frames(daemon: Path) -> None:
    from punt_lux.pty.menu_listener import TerminalMenu

    count = 4
    hub = StubHub()
    menu = TerminalMenu(hub.clients, DaemonExchange(daemon))

    async def scenario() -> None:
        task = asyncio.create_task(menu.serve())
        try:
            for _ in range(count):
                await menu._clicked("terminal")
            await _until(lambda: len(hub.scenes) == count)
        finally:
            task.cancel()

    asyncio.run(scenario())
    assert len({r.scene_id for r in hub.scenes.values()}) == count
    assert all(r.frame is None for r in hub.scenes.values())
