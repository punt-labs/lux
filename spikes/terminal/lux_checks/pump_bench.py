"""Benchmark the real PtyProcess.pump in a 60 fps frame loop: flood throughput + idle cost."""
import sys, time
from punt_lux.display.terminal.pty import PtyProcess

FRAME = 1 / 60
def run(argv, seconds, **kw):
    p = PtyProcess(argv, **kw)
    try:
        total, cost, frames = 0, 0.0, 0
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            t0 = time.monotonic(); total += len(p.pump()); cost += time.monotonic() - t0; frames += 1
            time.sleep(max(0.0, FRAME - (time.monotonic() - t0)))
        return total / seconds / 1e6, cost / frames * 1e3
    finally:
        p.close()

label = sys.argv[1]
mbs, ms = run(["/bin/sh", "-c", "exec yes 'the quick brown fox jumps over the lazy dog 0123456789'"], 3)
print(f"{label:12s} flood: {mbs:6.1f} MB/s  pump {ms:5.2f} ms/frame")
mbs, ms = run(["/bin/sh", "-c", "exec sleep 30"], 2)
print(f"{label:12s} idle:  pump {ms:5.3f} ms/frame")
