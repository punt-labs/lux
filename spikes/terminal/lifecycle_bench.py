"""20 short lifetime cycles with FD/RSS observations; not long-duration soak.

Run from spike root: timeout 90 .venv/bin/python -m spikes.terminal.lifecycle_bench
Uses one private daemon/socket, production replicas and owned programs only.
"""

from __future__ import annotations

import gc
import json
import os
import platform
import subprocess
import tempfile
import time
from pathlib import Path

from punt_lux.protocol.pty.control import WIRE_VERSION
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.replies import SuccessReply
from punt_lux.ptyd.snapshot import snapshot_version
from punt_lux.terminal.launcher import DaemonLauncher
from tests.ptyd.test_autostart_live import StartedDaemon
from tests.ptyd.test_lifecycle_cycles_live import LifecycleCycle
from tests.ptyd.wire_client import WireClient


class ResourceCycles:
    @staticmethod
    def resources(pid: int) -> dict[str, object]:
        output = subprocess.run(
            ["lsof", "-nP", "-p", str(pid), "-Ff"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
        descriptors = sorted(
            {
                int(line[1:])
                for line in output.splitlines()
                if line.startswith("f") and line[1:].isdigit()
            }
        )
        rss = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
        children = subprocess.run(
            ["pgrep", "-P", str(pid)], capture_output=True, text=True, timeout=5, check=False
        )
        assert children.returncode in (0, 1)
        return {
            "numeric_fd_count": len(descriptors),
            "numeric_fds": descriptors,
            "rss_kib": int(rss.strip()),
            "child_pids": [int(value) for value in children.stdout.split()],
        }

    @staticmethod
    def main() -> None:
        os.environ["LUX_PTY_NO_MENU"] = "1"  # headless resource check, no normal Hub
        report: dict[str, object] = {
            "platform": platform.platform(),
            "scope": "20 finite sequential lifecycle cycles; FD/RSS snapshots, not soak proof",
        }
        with tempfile.TemporaryDirectory(prefix="lxcycle-", dir="/tmp") as directory:
            path = Path(directory) / "p.sock"
            launcher = DaemonLauncher(path)
            client: WireClient | None = None
            try:
                launcher.ensure()
                StartedDaemon.ready(path)
                pid = launcher.child_pid
                assert pid is not None
                client = WireClient(path)
                assert isinstance(
                    client.request(HelloRequest(1, WIRE_VERSION, snapshot_version())), SuccessReply
                )
                cycles = []
                samples = []
                parent_before = ResourceCycles.resources(os.getpid())["numeric_fd_count"]
                for index in range(20):
                    cycles.append(LifecycleCycle.run(path, index, client))
                    if index in (1, 9, 19):
                        time.sleep(0.1)  # daemon purges closed viewer connections
                        gc.collect()
                        sample = ResourceCycles.resources(pid)
                        assert sample["child_pids"] == []
                        samples.append({"completed_cycles": index + 1, **sample})
                assert samples[0]["numeric_fd_count"] == samples[-1]["numeric_fd_count"]
                assert LifecycleCycle.sessions(client, 300) == []
                gc.collect()
                parent_after = ResourceCycles.resources(os.getpid())["numeric_fd_count"]
                assert parent_after == parent_before
                report.update(
                    daemon_pid=pid,
                    cycles=cycles,
                    daemon_resources=samples,
                    parent_fd_count_before=parent_before,
                    parent_fd_count_after=parent_after,
                )
            finally:
                if client is not None:
                    client.close()
                StartedDaemon.stop_owned(launcher)
            assert not path.exists()
            assert launcher.child_pid is None
        report["cleanup"] = (
            "programs reaped, owned daemon stopped/reaped, socket removed, private instance removed"
        )
        report["memory_note"] = (
            "RSS includes allocator/cache retention; "
            "short samples cannot prove absence of long-term leaks"
        )
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    ResourceCycles.main()
