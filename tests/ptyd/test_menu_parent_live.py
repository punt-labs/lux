"""Menu helper detects actual owner death without a PID-reuse liveness guess."""

from __future__ import annotations

import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_menu_helper_exits_if_owner_dies_before_or_after_helper_start() -> None:
    with tempfile.TemporaryDirectory(prefix="lxparent-", dir="/tmp") as directory:
        env = {**os.environ, "HOME": directory}
        ps = shutil.which("ps")
        assert ps is not None
        code = (
            "import os,sys,time; "
            "pid=os.posix_spawn(sys.executable,[sys.executable,'-m',"
            "'punt_lux.ptyd.menu_entry',str(os.getpid())],"
            "dict(os.environ)); "
            "print(pid,flush=True); time.sleep(30)"
        )
        owner = subprocess.Popen(
            [sys.executable, "-c", code],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        helper: int | None = None
        try:
            assert owner.stdout is not None
            assert select.select([owner.stdout], [], [], 3)[0]
            helper = int(owner.stdout.readline())
            owner.kill()
            owner.wait(timeout=3)
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                result = subprocess.run(
                    [ps, "-o", "command=", "-p", str(helper)],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                if "punt_lux.ptyd.menu_entry" not in result.stdout:
                    break
                time.sleep(0.05)
            else:
                pytest.fail("menu helper remained after its actual owner died")
            assert not (Path(directory) / ".punt-labs/lux/hub.port").exists()
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=3)
            if helper is not None:
                result = subprocess.run(
                    [ps, "-o", "command=", "-p", str(helper)],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                if f"punt_lux.ptyd.menu_entry {owner.pid}" in result.stdout:
                    os.kill(helper, signal.SIGKILL)
            if owner.stdout is not None:
                owner.stdout.close()
