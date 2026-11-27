"""A Display whose main thread is stuck in native code still stops on SIGTERM."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# The main thread blocks in a native sleep with SIGTERM masked, as an idle render
# loop that macOS has stopped repainting is stuck in native code: the signal
# reaches another thread and no Python handler can run on the main thread.
_STUCK_DISPLAY = """
import ctypes
import signal
from unittest.mock import MagicMock

from punt_lux.display.exit_signal import ExitSignal
from punt_lux.kernel.logging_config import process_diagnostics

with process_diagnostics("daemon", "probe display"):
    runner = MagicMock()
    runner.app_shall_exit = False
    ExitSignal(runner)
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    print("ready", flush=True)
    ctypes.CDLL(None).sleep(120)
"""


def test_a_display_stuck_in_native_code_logs_sigterm_and_exits(tmp_path: Path) -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", _STUCK_DISPLAY],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env={**os.environ, "HOME": str(tmp_path), "LUX_LOG_LEVEL": "INFO"},
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"
        process.send_signal(signal.SIGTERM)
        code = process.wait(timeout=20)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)

    log = (tmp_path / ".punt-labs/lux/logs/lux.log").read_text()
    assert code == 0
    assert "received SIGTERM" in log
    assert "did not exit" in log
