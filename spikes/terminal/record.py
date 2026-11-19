"""Record a program's PTY output as timestamped chunks (a minimal .cast-like file).

usage: uv run python record.py NAME COLS ROWS SECONDS [--keys KEYS] -- CMD...
Output: recordings/NAME.jsonl -- a header line then [t, base64-bytes] per chunk.
KEYS is a Python-literal bytes string sent after 1s (e.g. to quit an app).
"""

from __future__ import annotations

import argparse
import ast
import base64
import fcntl
import json
import os
import pty
import select
import struct
import termios
import time
from pathlib import Path


def record(name: str, cols: int, rows: int, seconds: float, keys: bytes, cmd: list[str]) -> Path:
    pid, fd = pty.fork()
    if pid == 0:
        env = dict(os.environ, TERM="xterm-256color", COLUMNS=str(cols), LINES=str(rows))
        env.pop("TERM_PROGRAM", None)
        os.execvpe(cmd[0], cmd, env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    chunks: list[tuple[float, bytes]] = []
    start = time.monotonic()
    sent = False
    while (now := time.monotonic() - start) < seconds:
        if keys and not sent and now > 1.0:
            os.write(fd, keys)
            sent = True
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            chunks.append((now, data))
    for sig in (15, 9):  # TERM, then KILL if it is still alive after 0.5s
        try:
            os.kill(pid, sig)
            for _ in range(10):
                if os.waitpid(pid, os.WNOHANG)[0]:
                    break
                time.sleep(0.05)
            else:
                continue
            break
        except (ProcessLookupError, ChildProcessError):
            break
    os.close(fd)
    out = Path(__file__).parent / "recordings" / f"{name}.jsonl"
    out.parent.mkdir(exist_ok=True)
    with out.open("w") as f:
        f.write(json.dumps({"cols": cols, "rows": rows, "cmd": cmd}) + "\n")
        for t, data in chunks:
            f.write(json.dumps([round(t, 4), base64.b64encode(data).decode()]) + "\n")
    total = sum(len(d) for _, d in chunks)
    print(f"{name}: {len(chunks)} chunks, {total:,} bytes -> {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("cols", type=int)
    ap.add_argument("rows", type=int)
    ap.add_argument("seconds", type=float)
    ap.add_argument("--keys", default="b''")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    record(a.name, a.cols, a.rows, a.seconds, ast.literal_eval(a.keys), cmd)


if __name__ == "__main__":
    main()
