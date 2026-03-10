"""Font coverage test — start dev display server on the default socket.

Kills any running display server and starts one from the local dev source,
so font changes can be tested via normal MCP tools. Run via: make font-test
"""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

SOCK_DIR = Path("/tmp/lux-jfreeman")
SOCK_PATH = SOCK_DIR / "display.sock"
PID_PATH = SOCK_DIR / "display.pid"


def main() -> None:
    # Kill existing display server
    if PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text().strip())
            print(f"Killing existing display server (PID {pid})...")
            import os

            os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
        except (ValueError, ProcessLookupError, OSError):
            pass

    # Clean stale files
    SOCK_PATH.unlink(missing_ok=True)
    PID_PATH.unlink(missing_ok=True)
    SOCK_DIR.mkdir(parents=True, exist_ok=True)

    # Start display server from local dev source
    print("Starting dev display server...")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "punt_lux",
            "display",
            "--socket",
            str(SOCK_PATH),
        ],
    )

    # Wait for socket
    for _ in range(50):
        if SOCK_PATH.exists():
            break
        time.sleep(0.1)
    else:
        print("ERROR: display server did not start")
        proc.kill()
        sys.exit(1)

    print(f"Dev display server running (PID {proc.pid})")
    print("Use MCP show tool to send test scenes. Ctrl+C to stop.")

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    main()
