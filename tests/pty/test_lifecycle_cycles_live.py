"""Short repeated lifetime cycles; this is not a long-duration memory soak."""

from __future__ import annotations

import shlex
import sys
import time
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
from tests.pty.test_remote_live import PoolWait
from tests.pty.wire_client import WireClient

pytestmark = pytest.mark.integration

COMMAND = shlex.join(
    [
        sys.executable,
        "-u",
        "-c",
        """
import sys
print('CYCLE_READY',flush=True)
for line in sys.stdin:
    if line.strip()=='exit':
        break
    print('ECHO:'+line.strip(),flush=True)
""",
    ]
)


class LifecycleCycle:
    @staticmethod
    def sessions(client: WireClient, request_id: int) -> list[object]:
        reply = client.request(ListRequest(request_id))
        assert isinstance(reply, SuccessReply)
        sessions = reply.result["sessions"]
        assert isinstance(sessions, list)
        return sessions

    @staticmethod
    def run(
        path: Path, index: int, client: WireClient, launch: Launch
    ) -> dict[str, object]:
        name = launch.session(COMMAND)
        first = RemotePool(path)
        try:
            session = first.get(name, "")
            PoolWait.until(
                first,
                lambda: (
                    session.phase is RemotePhase.READY
                    and "CYCLE_READY" in session.view.term.text()
                ),
            )
            pid = PoolWait.pid(path)
            session.write(b"round\n")
            PoolWait.until(first, lambda: "ECHO:round" in session.view.term.text())
            exited = index % 3 == 0
            if exited:
                session.write(b"exit\n")
                PoolWait.until(first, lambda: session.phase is RemotePhase.EXITED)
        finally:
            first.close()
        second = RemotePool(path)
        try:
            replica = second.get(name, "")
            if exited:
                PoolWait.until(second, lambda: replica.phase is RemotePhase.FAILED)
                assert "unknown session" in replica.status
            else:
                PoolWait.until(second, lambda: replica.phase is RemotePhase.READY)
                assert PoolWait.pid(path) == pid
                assert "ECHO:round" in replica.view.term.text()
                replica.write(b"again\n")
                PoolWait.until(second, lambda: "ECHO:again" in replica.view.term.text())
        finally:
            second.close()
        assert isinstance(
            client.request(KillRequest(100 + index * 2, name)), SuccessReply
        )
        deadline = time.monotonic() + 5
        while (
            LifecycleCycle.sessions(client, 101 + index * 2)
            and time.monotonic() < deadline
        ):
            time.sleep(0.005)
        assert LifecycleCycle.sessions(client, 101 + index * 2) == []
        return {"cycle": index, "pid": pid, "exited_before_reattach": exited}


def test_repeated_create_detach_reattach_exit_and_kill(
    daemon: Path, launch: Launch
) -> None:
    client = WireClient(daemon)
    try:
        assert isinstance(
            client.request(HelloRequest(1, WIRE_VERSION, snapshot_version())),
            SuccessReply,
        )
        for index in range(5):
            LifecycleCycle.run(daemon, index, client, launch)
    finally:
        client.close()
