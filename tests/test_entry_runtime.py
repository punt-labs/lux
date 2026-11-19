"""Exercise the diagnostics lifecycle used by both Lux daemons."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def test_daemon_runtime_records_failure_and_flushes_usage(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from punt_lux.entry_runtime import DaemonRuntime\n"
                "from punt_lux.usage import record_first_paint\n"
                "with DaemonRuntime('test-daemon').run():\n"
                "    record_first_paint(100)\n"
                "    raise RuntimeError('private startup error')\n"
            ),
        ],
        stderr=subprocess.DEVNULL,
        check=False,
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "LUX_LOG_LEVEL": "INFO",
            "LUX_TELEMETRY": "on",
            "PUNT_TELEMETRY": "on",
        },
    )
    assert result.returncode == 1
    state = tmp_path / ".punt-labs" / "lux"
    log = (state / "logs" / "lux.log").read_text()
    assert "test-daemon failed: RuntimeError" in log
    assert "private startup error" not in log
    with closing(sqlite3.connect(state / "telemetry.db")) as db:
        assert db.execute("SELECT name, sum FROM metric_points").fetchall() == [
            ("lux.display.first_paint_duration", 100.0)
        ]
