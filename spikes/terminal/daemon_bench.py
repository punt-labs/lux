"""Bounded production-replica measurements, not GUI FPS or WAN benchmarks.

Run from the spike root: timeout 45 .venv/bin/python -m spikes.terminal.daemon_bench
The independent daemon/programs use one private temporary socket. Output is a
finite paced 8 MiB burst, never an endless writer. Cleanup targets owned children.
"""

from __future__ import annotations

import json
import math
import platform
import shlex
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path

from punt_lux.display.terminal.remote import RemoteSession
from punt_lux.display.terminal.remote_phase import RemotePhase
from punt_lux.display.terminal.remote_pool import RemotePool
from punt_lux.terminal.ffi_snapshot import NativeSnapshotCodec
from tests.ptyd.test_autostart_live import StartedDaemon


class Measurements:
    @staticmethod
    def visible(session: RemoteSession) -> str:
        return NativeSnapshotCodec.active_screen_vt(session.view.term).decode()

    @staticmethod
    def summary(values: list[float]) -> dict[str, float | int]:
        ordered = sorted(values)
        return {
            "samples": len(values),
            "median_ms": round(statistics.median(ordered) * 1000, 3),
            "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1] * 1000, 3),
            "max_ms": round(ordered[-1] * 1000, 3),
        }

    @staticmethod
    def wait(pool: RemotePool, condition: Callable[[], bool]) -> None:
        end = time.monotonic() + 8
        while time.monotonic() < end:
            pool.pump()
            if condition():
                return
            time.sleep(0.001)
        raise TimeoutError("replica measurement deadline exceeded")

    @staticmethod
    def command(code: str) -> str:
        return shlex.join([sys.executable, "-u", "-c", code])

    @staticmethod
    def main() -> None:
        report: dict[str, object] = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "pyghostty": version("pyghostty"),
            "scope": "production RemotePool, native replicas, local Unix socket; no GUI rendering",
        }
        with tempfile.TemporaryDirectory(prefix="lxbench-", dir="/tmp") as directory:
            path = Path(directory) / "p.sock"
            pool = RemotePool(path)
            launcher = pool._connector._launcher
            try:
                started = time.monotonic()
                shell_command = Measurements.command(
                    "import sys; print('RESTORE_READY',flush=True); sys.stdin.readline()"
                )
                session = pool.get("restore", shell_command)
                Measurements.wait(pool, lambda: "RESTORE_READY" in Measurements.visible(session))
                report["cold_start_ms"] = round((time.monotonic() - started) * 1000, 3)
                reconnect: list[float] = []
                for _ in range(10):
                    pool.close()
                    pool = RemotePool(path)
                    started = time.monotonic()
                    session = pool.get("restore", shell_command)
                    Measurements.wait(
                        pool,
                        lambda session=session: (
                            session.phase is RemotePhase.READY
                            and "RESTORE_READY" in Measurements.visible(session)
                        ),
                    )
                    reconnect.append(time.monotonic() - started)
                report["warm_reattach"] = Measurements.summary(reconnect)
                flood = pool.get(
                    "flood",
                    Measurements.command(
                        "import sys,time; print('FLOOD_READY',flush=True); "
                        "sys.stdin.readline(); chunk='x'*79+'\\n'; "
                        "[(sys.stdout.write(chunk*204),sys.stdout.flush(),time.sleep(.001)) "
                        "for _ in range(514)]; print('FLOOD_END',flush=True); sys.stdin.readline()"
                    ),
                )
                probe = pool.get(
                    "probe",
                    Measurements.command(
                        "import sys; print('PROBE_READY',flush=True); "
                        "[print('R:'+line.strip(),flush=True) for line in sys.stdin]"
                    ),
                )
                Measurements.wait(
                    pool,
                    lambda: (
                        "FLOOD_READY" in Measurements.visible(flood)
                        and "PROBE_READY" in Measurements.visible(probe)
                    ),
                )
                baseline: list[float] = []
                for index in range(10):
                    marker = "B" + str(index)
                    sent = time.monotonic()
                    probe.write((marker + "\n").encode())
                    Measurements.wait(
                        pool,
                        lambda marker=marker: "R:" + marker in Measurements.visible(probe),
                    )
                    baseline.append(time.monotonic() - sent)
                report["input_to_response_without_burst"] = Measurements.summary(baseline)
                flood.write(b"go\n")
                started = time.monotonic()
                deadline = started + 10
                pump_times: list[float] = []
                latency: list[float] = []
                pending: tuple[str, float] | None = None
                next_probe = started
                while time.monotonic() < deadline:
                    now = time.monotonic()
                    pool.pump()
                    pump_times.append(time.monotonic() - now)
                    done = "FLOOD_END" in Measurements.visible(flood)
                    if pending is not None and "R:" + pending[0] in Measurements.visible(probe):
                        latency.append(time.monotonic() - pending[1])
                        pending = None
                    if done and pending is None:
                        break
                    if not done and pending is None and now >= next_probe:
                        marker = "Q" + str(len(latency))
                        pending = (marker, time.monotonic())
                        probe.write((marker + "\n").encode())
                        next_probe = now + 0.015
                    time.sleep(0.001)
                else:
                    raise TimeoutError("finite output burst did not finish")
                assert len(latency) >= 10, "not enough probes overlapped the finite burst"
                report["finite_burst"] = {
                    "payload_bytes": 80 * 204 * 514,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                    "input_to_response_during_burst": Measurements.summary(latency),
                    "pool_pump_during_burst": Measurements.summary(pump_times),
                    "replica_bytes_received": flood.bytes_in,
                }
            finally:
                pool.close()
                StartedDaemon.stop_owned(launcher)
            assert not path.exists()
        report["cleanup"] = "owned daemon stopped; programs reaped; private instance removed"
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    Measurements.main()
