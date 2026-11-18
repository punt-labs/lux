"""The Display-side replica pool leaves the daemon-owned program running."""

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
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.replies import SuccessReply
from punt_lux.protocol.pty.session_requests import KillRequest, ListRequest
from punt_lux.ptyd.snapshot import snapshot_version
from tests.ptyd.wire_client import WireClient

pytestmark = pytest.mark.integration


class PoolWait:
    @staticmethod
    def until(pool: RemotePool, condition: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pool.pump()
            if condition():
                return
            time.sleep(0.005)
        pytest.fail("Display replica did not reach expected state")

    @staticmethod
    def pid(path: Path) -> object:
        client = WireClient(path)
        try:
            assert isinstance(
                client.request(HelloRequest(1, 1, snapshot_version())), SuccessReply
            )
            reply = client.request(ListRequest(2))
            assert isinstance(reply, SuccessReply)
            sessions = reply.result["sessions"]
            assert isinstance(sessions, list)
            return sessions[0]["pid"]
        finally:
            client.close()


def test_new_replica_pool_reattaches_to_the_same_process_and_screen(
    daemon: Path,
) -> None:
    code = (
        "import sys; print('READY',flush=True); "
        "line=sys.stdin.readline(); print('ECHO:'+line.strip(),flush=True); "
        "sys.stdin.readline()"
    )
    command = shlex.join([sys.executable, "-u", "-c", code])
    first = RemotePool(daemon)
    try:
        session = first.get("display", command)
        PoolWait.until(
            first,
            lambda: (
                session.phase is RemotePhase.READY
                and "READY" in session.view.term.text()
            ),
        )
        original_pid = PoolWait.pid(daemon)
        session.write(b"hello\n")
        PoolWait.until(first, lambda: "ECHO:hello" in session.view.term.text())
    finally:
        first.close()
    time.sleep(0.05)
    second = RemotePool(daemon)
    try:
        session = second.get("display", command)
        PoolWait.until(second, lambda: session.phase is RemotePhase.READY)
        assert PoolWait.pid(daemon) == original_pid
        assert "ECHO:hello" in session.view.term.text()
    finally:
        second.close()
    client = WireClient(daemon)
    try:
        client.request(HelloRequest(1, 1, snapshot_version()))
        assert isinstance(client.request(KillRequest(2, "display")), SuccessReply)
    finally:
        client.close()


def test_exited_program_stays_exited_after_new_replica_attaches(daemon: Path) -> None:
    command = shlex.join([sys.executable, "-u", "-c", "print('finished')"])
    first = RemotePool(daemon)
    try:
        session = first.get("exit", command)
        PoolWait.until(first, lambda: session.phase is RemotePhase.EXITED)
        assert "finished" in session.view.term.text()
        original_pid = PoolWait.pid(daemon)
    finally:
        first.close()
    time.sleep(0.05)
    second = RemotePool(daemon)
    try:
        session = second.get("exit", command)
        PoolWait.until(second, lambda: session.phase is RemotePhase.EXITED)
        assert PoolWait.pid(daemon) == original_pid
        assert "finished" in session.view.term.text()
    finally:
        second.close()
