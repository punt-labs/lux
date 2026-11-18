"""A Display-side pool starts a missing owner without operator intervention."""

from __future__ import annotations

import shlex
import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("pyghostty")
pytest.importorskip("imgui_bundle")

from punt_lux.display.terminal.remote_phase import RemotePhase
from punt_lux.display.terminal.remote_pool import RemotePool
from punt_lux.protocol.pty.control import WIRE_VERSION
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.replies import SuccessReply
from punt_lux.protocol.pty.session_requests import KillRequest
from punt_lux.ptyd.snapshot import snapshot_version
from tests.ptyd.test_autostart_live import StartedDaemon
from tests.ptyd.test_remote_live import PoolWait
from tests.ptyd.wire_client import WireClient

pytestmark = pytest.mark.integration


def test_first_terminal_starts_detached_daemon() -> None:
    with tempfile.TemporaryDirectory(prefix="lxpool-", dir="/tmp") as directory:
        path = Path(directory) / "p.sock"
        command = shlex.join(
            [
                sys.executable,
                "-u",
                "-c",
                "import sys; print('AUTO',flush=True); sys.stdin.readline()",
            ]
        )
        pool = RemotePool(path)
        try:
            session = pool.get("auto", command)
            PoolWait.until(
                pool,
                lambda: (
                    session.phase is RemotePhase.READY
                    and "AUTO" in session.view.term.text()
                ),
            )
            pool.close()
            client = WireClient(path)
            try:
                assert isinstance(
                    client.request(HelloRequest(1, WIRE_VERSION, snapshot_version())),
                    SuccessReply,
                )
                assert isinstance(client.request(KillRequest(2, "auto")), SuccessReply)
            finally:
                client.close()
        finally:
            pool.close()
            StartedDaemon.stop_owned(pool._connector._launcher)
        assert not path.exists()
