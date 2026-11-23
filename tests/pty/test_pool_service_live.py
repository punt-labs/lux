"""Display connects to an available owner, never enables one on a machine."""

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
from tests.pty.test_remote_live import PoolWait

pytestmark = pytest.mark.integration


def test_missing_service_is_not_started_by_display() -> None:
    with tempfile.TemporaryDirectory(prefix="lxdisabled-", dir="/tmp") as directory:
        path = Path(directory) / "p.sock"
        pool = RemotePool(path)
        try:
            session = pool.get("missing", "")
            pool.pump()
            assert session.phase is RemotePhase.DISCONNECTED
            assert not path.exists()
            assert not Path(str(path) + ".lock").exists()
        finally:
            pool.close()


def test_terminal_connects_to_running_machine_owner(daemon: Path) -> None:
    command = shlex.join(
        [
            sys.executable,
            "-u",
            "-c",
            "import sys; print('SERVICE_READY',flush=True); sys.stdin.readline()",
        ]
    )
    pool = RemotePool(daemon)
    try:
        session = pool.get("service", command)
        PoolWait.until(
            pool,
            lambda: (
                session.phase is RemotePhase.READY
                and "SERVICE_READY" in session.view.term.text()
            ),
        )
    finally:
        pool.close()
    assert daemon.exists()  # Display close does not stop the machine service
