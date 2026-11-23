"""Independent daemon fixture with bounded startup and teardown."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def no_normal_hub_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test owners never register callbacks with the operator's normal Hub."""
    monkeypatch.setenv("LUX_PTY_NO_MENU", "1")


@pytest.fixture
def daemon() -> Iterator[Path]:
    temporary = tempfile.TemporaryDirectory(prefix="lxpty-", dir="/tmp")
    path = Path(temporary.name) / "private" / "pty.sock"
    process = subprocess.Popen(
        [sys.executable, "-m", "punt_lux.pty", "--no-menu", "--socket", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            assert process.poll() is None, "daemon exited during startup"
            time.sleep(0.01)
        assert path.exists(), "daemon did not bind its socket"
        yield path
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        assert process.stderr is not None
        errors = process.stderr.read().decode("utf-8", "replace")
        process.stderr.close()
        assert process.returncode == 0, errors
        assert not path.exists(), "daemon left its endpoint behind"
        temporary.cleanup()
