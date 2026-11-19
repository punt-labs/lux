"""Measure PTY read throughput for one draining strategy, in a frame-like loop.

usage: pty_throughput.py STRATEGY [SECONDS]
  STRATEGY: ready   -- read only what is ready right now (the spike's original)
            budget  -- keep reading for up to 2 ms per frame (round 1)
            wake    -- 'budget', plus wait up to 2 ms for more before giving up (round 2)

Safe by construction: the child is killed in a finally block, every read is
non-blocking, and the whole run is capped at SECONDS (default 3). Run it under
`timeout` as well.
"""

from __future__ import annotations

import os
import select
import signal
import sys
import time

FRAME_S = 1 / 60
CAP = 4 << 20  # bytes per frame, at most
CMD = ["/bin/sh", "-c", "exec yes 'the quick brown fox jumps over the lazy dog 0123456789'"]


def read_ready(fd: int) -> int:
    n = 0
    while n < CAP:
        if not select.select([fd], [], [], 0)[0]:
            return n
        try:
            n += len(os.read(fd, 65536))
        except BlockingIOError:
            return n
    return n


def read_budget(fd: int, budget_s: float = 0.002, wait_s: float = 0.0) -> int:
    """Read until the budget runs out, the cap is hit, or nothing comes for wait_s."""
    n = 0
    deadline = time.monotonic() + budget_s
    while n < CAP and (left := deadline - time.monotonic()) > 0:
        if not select.select([fd], [], [], min(wait_s, left))[0]:
            break
        try:
            n += len(os.read(fd, 65536))
        except BlockingIOError:
            break
    return n


STRATEGIES = {
    "ready": read_ready,
    "budget": lambda fd: read_budget(fd, 0.002, 0.0),
    "wake": lambda fd: read_budget(fd, 0.002, 0.002),
    # round 2: same idea, different per-frame time budgets
    "wake1": lambda fd: read_budget(fd, 0.001, 0.001),
    "wake4": lambda fd: read_budget(fd, 0.004, 0.002),
    "wake8": lambda fd: read_budget(fd, 0.008, 0.002),
}


def main() -> None:
    name = sys.argv[1]
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    read = STRATEGIES[name]
    import pty

    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(CMD[0], CMD)
    try:
        os.set_blocking(fd, False)
        total, frames, read_ms = 0, 0, 0.0
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            t0 = time.monotonic()
            total += read(fd)
            read_ms += (time.monotonic() - t0) * 1e3
            frames += 1
            rest = FRAME_S - (time.monotonic() - t0)  # the rest of the frame (render, swap)
            if rest > 0:
                time.sleep(rest)
        print(
            f"{name:7s} {total / seconds / 1e6:7.1f} MB/s   "
            f"read {read_ms / frames:5.2f} ms/frame   {frames} frames"
        )
    finally:
        # Close the PTY *before* reaping: a killed child with unread output on
        # an open PTY may not finish exiting, and a blocking waitpid hangs.
        os.close(fd)
        os.kill(pid, signal.SIGKILL)
        for _ in range(50):  # never block: poll for up to 1 s
            if os.waitpid(pid, os.WNOHANG)[0]:
                break
            time.sleep(0.02)


if __name__ == "__main__":
    main()
