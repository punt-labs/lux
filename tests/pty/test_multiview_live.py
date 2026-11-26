"""Several Display-side viewers share one held process and authoritative size."""

from __future__ import annotations

import shlex
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

pytest.importorskip("pyghostty")
pytest.importorskip("imgui_bundle")

from punt_lux.display.terminal.remote_phase import RemotePhase
from punt_lux.display.terminal.remote_pool import RemotePool
from tests.pty.launchers import Launch
from tests.pty.test_remote_live import PoolWait

pytestmark = pytest.mark.integration


class BothPools:
    @staticmethod
    def until(first: RemotePool, second: RemotePool, check: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            first.pump()
            second.pump()
            if check():
                return
            time.sleep(0.005)
        pytest.fail("viewers did not converge")


def test_two_viewers_share_screen_and_resize_without_respawn(
    daemon: Path, launch: Launch
) -> None:
    code = (
        "import sys; print('READY',flush=True); "
        "line=sys.stdin.readline(); print('ECHO:'+line.strip(),flush=True); "
        "sys.stdin.readline()"
    )
    name = launch.session(shlex.join([sys.executable, "-u", "-c", code]))
    first, second = RemotePool(daemon), RemotePool(daemon)
    try:
        a, b = first.get(name, ""), second.get(name, "")
        BothPools.until(
            first,
            second,
            lambda: a.phase is RemotePhase.READY and b.phase is RemotePhase.READY,
        )
        pid = PoolWait.pid(daemon)
        a.resize(40, 8)
        BothPools.until(first, second, lambda: a.view.size == b.view.size == (40, 8))
        a.write(b"hello\n")
        BothPools.until(
            first,
            second,
            lambda: (
                "ECHO:hello" in a.view.term.text()
                and "ECHO:hello" in b.view.term.text()
            ),
        )
        assert PoolWait.pid(daemon) == pid
        assert a.view.term.text() == b.view.term.text()
        first.close()
        second.pump()
        assert b.phase is RemotePhase.READY
    finally:
        first.close()
        second.close()
