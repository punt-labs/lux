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
from punt_lux.terminal.snapshot import snapshot_version
from punt_lux.wire.stream.control import WIRE_VERSION
from punt_lux.wire.stream.hello import HelloRequest
from punt_lux.wire.stream.replies import SuccessReply
from punt_lux.wire.stream.session_requests import KillRequest, ListRequest
from tests.pty.launchers import Launch
from tests.pty.wire_client import WireClient

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
                client.request(HelloRequest(1, WIRE_VERSION, snapshot_version())),
                SuccessReply,
            )
            reply = client.request(ListRequest(2))
            assert isinstance(reply, SuccessReply)
            sessions = reply.result["sessions"]
            assert isinstance(sessions, list)
            return sessions[0]["pid"]
        finally:
            client.close()


def test_new_replica_pool_reattaches_to_the_same_process_and_screen(
    daemon: Path, launch: Launch
) -> None:
    code = (
        "import sys; print('READY',flush=True); "
        "line=sys.stdin.readline(); print('ECHO:'+line.strip(),flush=True); "
        "sys.stdin.readline()"
    )
    name = launch.session(shlex.join([sys.executable, "-u", "-c", code]))
    first = RemotePool(daemon)
    try:
        session = first.get(name, "")
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
        session = second.get(name, "")
        PoolWait.until(second, lambda: session.phase is RemotePhase.READY)
        assert PoolWait.pid(daemon) == original_pid
        assert "ECHO:hello" in session.view.term.text()
    finally:
        second.close()
    client = WireClient(daemon)
    try:
        client.request(HelloRequest(1, WIRE_VERSION, snapshot_version()))
        assert isinstance(client.request(KillRequest(2, name)), SuccessReply)
    finally:
        client.close()


def test_exited_program_refuses_a_new_replica_and_never_respawns(
    daemon: Path, launch: Launch
) -> None:
    code = "import sys; sys.stdin.readline(); print('finished')"
    name = launch.session(shlex.join([sys.executable, "-u", "-c", code]))
    first = RemotePool(daemon)
    try:
        session = first.get(name, "")
        PoolWait.until(first, lambda: session.phase is RemotePhase.READY)
        session.write(b"go\n")
        PoolWait.until(first, lambda: session.phase is RemotePhase.EXITED)
        assert "finished" in session.view.term.text()
    finally:
        first.close()
    second = RemotePool(daemon)
    try:
        replica = second.get(name, "")
        PoolWait.until(second, lambda: replica.phase is RemotePhase.FAILED)
        assert "unknown session" in replica.status
    finally:
        second.close()
    client = WireClient(daemon)
    try:
        client.request(HelloRequest(1, WIRE_VERSION, snapshot_version()))
        reply = client.request(ListRequest(2))
        assert isinstance(reply, SuccessReply)
        sessions = reply.result["sessions"]
        assert isinstance(sessions, list)
        assert [s["session"] for s in sessions] == [name]  # nothing was respawned
    finally:
        client.close()
