"""Font coverage test — start dev display server on the default socket.

Kills any running display server and starts one from the local dev source,
so font changes can be tested via normal MCP tools. Run via: make font-test
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from punt_lux.paths import (
    cleanup_stale_socket,
    default_socket_path,
    is_display_running,
    pid_file_path,
)

SOCK_PATH = default_socket_path()
PID_PATH = pid_file_path(SOCK_PATH)


def _kill_existing() -> None:
    """Kill existing display server if running, with SIGKILL escalation."""
    if not (is_display_running(SOCK_PATH) and SOCK_PATH.is_socket()):
        return

    try:
        pid = int(PID_PATH.read_text().strip())
    except (OSError, ValueError):
        return

    print(f"Killing existing display server (PID {pid})...")
    os.kill(pid, signal.SIGTERM)

    for _ in range(20):
        if not is_display_running(SOCK_PATH):
            return
        time.sleep(0.25)

    os.kill(pid, signal.SIGKILL)
    for _ in range(20):
        if not is_display_running(SOCK_PATH):
            return
        time.sleep(0.1)

    print("ERROR: existing display server would not exit")
    sys.exit(1)


def main() -> None:
    _kill_existing()
    cleanup_stale_socket(SOCK_PATH)
    SOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

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
        proc.wait()
        sys.exit(1)

    print(f"Dev display server running (PID {proc.pid})")
    print("Use MCP show tool to send test scenes. Ctrl+C to stop.")

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


if __name__ == "__main__":
    main()
