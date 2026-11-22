"""Detached launch, concurrent contenders and real empty-only idle exit."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

pytest.importorskip("pyghostty")

from punt_lux.protocol.pty.control import WIRE_VERSION
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.replies import SuccessReply
from punt_lux.terminal.launcher import DaemonLauncher
from tests.ptyd.wire_client import WireClient

pytestmark = pytest.mark.integration


class StartedDaemon:
    @staticmethod
    def ready(path: Path) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                client = WireClient(path)
            except OSError:
                time.sleep(0.01)
                continue
            try:
                from punt_lux.terminal.snapshot import snapshot_version

                reply = client.request(
                    HelloRequest(1, WIRE_VERSION, snapshot_version())
                )
                assert isinstance(reply, SuccessReply)
                return
            finally:
                client.close()
        pytest.fail("auto-started daemon did not become ready")

    @staticmethod
    def stop_owned(launcher: DaemonLauncher) -> None:
        launcher.poll()
        pid = launcher.child_pid
        if pid is not None:
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                launcher.poll()
                if launcher.child_pid is None:
                    return
                time.sleep(0.01)
            os.kill(pid, signal.SIGKILL)
            pytest.fail("owned daemon did not stop")


def test_simultaneous_launchers_leave_one_live_daemon() -> None:
    with tempfile.TemporaryDirectory(prefix="lxstart-", dir="/tmp") as directory:
        path = Path(directory) / "p.sock"
        first, second = DaemonLauncher(path), DaemonLauncher(path)
        try:
            first.ensure()
            second.ensure()
            StartedDaemon.ready(path)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                first.poll()
                second.poll()
                if (first.child_pid is None) != (second.child_pid is None):
                    break
                time.sleep(0.01)
            assert (first.child_pid is None) != (second.child_pid is None)
        finally:
            StartedDaemon.stop_owned(first)
            StartedDaemon.stop_owned(second)
        assert not path.exists()


def test_crashed_daemon_stale_socket_is_reclaimed() -> None:
    with tempfile.TemporaryDirectory(prefix="lxstale-", dir="/tmp") as directory:
        path = Path(directory) / "p.sock"
        first, replacement = DaemonLauncher(path), DaemonLauncher(path)
        try:
            first.ensure()
            StartedDaemon.ready(path)
            first.poll()
            pid = first.child_pid
            assert pid is not None
            assert os.getsid(pid) == pid
            os.kill(pid, signal.SIGKILL)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and first.child_pid is not None:
                first.poll()
                time.sleep(0.01)
            assert first.child_pid is None
            assert path.exists()
            replacement.ensure()
            StartedDaemon.ready(path)
        finally:
            StartedDaemon.stop_owned(first)
            StartedDaemon.stop_owned(replacement)
        assert not path.exists()


def test_empty_daemon_exits_but_attached_client_prevents_idle() -> None:
    with tempfile.TemporaryDirectory(prefix="lxidle-", dir="/tmp") as directory:
        path = Path(directory) / "p.sock"
        code = (
            "import signal; from pathlib import Path; "
            "from punt_lux.ptyd.server import PtyServer; "
            f"server=PtyServer(Path({str(path)!r}),idle_timeout=0.2); "
            "assert server.client_count==0 and server.session_count==0; "
            "signal.signal(signal.SIGTERM,lambda *_:server.stop()); server.run()"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        client: WireClient | None = None
        try:
            StartedDaemon.ready(path)
            client = WireClient(path)
            time.sleep(0.35)
            assert process.poll() is None
            client.close()
            client = None
            assert process.wait(timeout=3) == 0
            assert not path.exists()
        finally:
            if client is not None:
                client.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            assert process.stderr is not None
            errors = process.stderr.read().decode()
            process.stderr.close()
            assert process.returncode == 0, errors
