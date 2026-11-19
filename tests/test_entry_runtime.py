"""Exercise Lux daemon diagnostics and telemetry teardown."""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from typing import TYPE_CHECKING

import httpx
import pytest

from punt_lux.hub_paths import HubPaths

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


@pytest.mark.integration
def test_hub_flushes_render_metrics_on_sigterm(tmp_path: Path) -> None:
    state = tmp_path / ".punt-labs" / "lux"
    paths = HubPaths(state)
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "PUNT_TELEMETRY": "on",
        "LUX_TELEMETRY": "on",
        "PUNT_TELEMETRY_EXPORTER": "sqlite",
    }
    command = [
        sys.executable,
        "-c",
        "from punt_lux.luxd import main; main()",
        "--port",
        "0",
    ]
    with subprocess.Popen(command, cwd=tmp_path, env=env) as hub:
        try:
            deadline = time.monotonic() + 20
            port = paths.read_port()
            while port is None and hub.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
                port = paths.read_port()
            assert port is not None, f"Hub did not bind (exit={hub.poll()})"
            response = httpx.put(
                f"http://127.0.0.1:{port}/scenes/flush-test",
                json={"scene_id": "flush-test", "elements": []},
                headers={"X-Lux-Client-Kind": "cli", "X-Lux-Client-Name": "test"},
                timeout=5,
                trust_env=False,
            )
            assert response.status_code == 200
            assert response.json() == {"kind": "ok", "scene_id": "flush-test"}
            with closing(sqlite3.connect(state / "telemetry.db")) as db:
                before_shutdown = db.execute("SELECT count(*) FROM metric_points")
                assert before_shutdown.fetchone() == (0,)
            hub.terminate()
            assert hub.wait(timeout=20) == -signal.SIGTERM
        finally:
            if hub.poll() is None:
                hub.kill()
                hub.wait()

    with closing(sqlite3.connect(state / "telemetry.db")) as db:
        assert db.execute("SELECT name, count FROM metric_points").fetchall() == [
            ("lux.hub.operation_duration", 1)
        ]
