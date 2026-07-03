"""Subprocess lifecycle smoke — Text scene survives end-to-end.

DisplayClient keeps its existing length-prefixed framing; the
``Connection`` module is a parallel transport consumed by tests only.

This smoke test spawns the display via :class:`DisplayPaths.ensure`, sends
one Text scene through the unchanged DisplayClient path, closes the
client, terminates the subprocess, and asserts the PID file is gone. It
guards the Element ABC path for TextElement end-to-end — if the wire
shape or codec dispatch regressed, the scene ack would never arrive.
"""

from __future__ import annotations

import os
import shutil
import signal
import tempfile
import time
from pathlib import Path

import pytest

from punt_lux.display_client import DisplayClient
from punt_lux.paths import DisplayPaths
from punt_lux.protocol import TextElement


def _short_sock_path() -> tuple[str, Path]:
    """Return ``(tmpdir, sock_path)`` short enough for AF_UNIX (~104 chars)."""
    d = tempfile.mkdtemp(prefix="lux-")
    return d, Path(d) / "d.sock"


def _wait_pid_gone(pid_path: Path, timeout: float = 5.0) -> bool:
    """Poll until ``pid_path`` is removed or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_path.exists():
            return True
        time.sleep(0.05)
    return False


@pytest.mark.e2e
def test_text_scene_survives_subprocess_lifecycle() -> None:
    """Spawn display, send Text scene, shut down, assert PID file removed."""
    short_dir, sock_path = _short_sock_path()
    paths = DisplayPaths(sock_path)
    pid_path = paths.pid_path

    try:
        paths.ensure(timeout=10.0)
        assert paths.is_running()
        assert pid_path.exists()

        with DisplayClient(sock_path, auto_spawn=False, connect_timeout=5.0) as client:
            assert client.is_connected
            ack = client.show(
                "lifecycle-smoke",
                elements=[TextElement(id="t1", content="Hello, lifecycle.")],
                title="Lifecycle Smoke",
            )
            assert ack is not None
            assert ack.scene_id == "lifecycle-smoke"

        # Terminate the subprocess via its PID file — the display server's
        # SIGTERM handler removes the PID file before exiting.
        pid = int(pid_path.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        assert _wait_pid_gone(pid_path), f"PID file still present at {pid_path}"
    finally:
        # Best-effort cleanup if the assertion above failed or the process
        # is still around.
        if pid_path.exists():
            try:
                pid = int(pid_path.read_text().strip())
                os.kill(pid, signal.SIGKILL)
            except (ValueError, ProcessLookupError, OSError):
                pass
        shutil.rmtree(short_dir, ignore_errors=True)
