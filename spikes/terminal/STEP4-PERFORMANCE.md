# Step 4: measured local responsiveness

These are finite, isolated observations, not product latency guarantees or WAN
throughput claims. macOS 26.6.2 arm64, Python 3.14.0, pyghostty 0.1.4. Each run
stops its owned daemon/programs and removes its private instance.

## Production replicas, without a GUI render loop

```sh
timeout 45 .venv/bin/python -m spikes.terminal.daemon_bench
```

The benchmark uses the production RemotePool, native Ghostty replicas and a
local Unix socket. A separate probe program shares the pool with a finite
8,388,480-byte output program. Probe latency is input submission to an explicit
program response, not the PTY's local echo. Active-grid formatting is used for
observation, not repeated whole-scrollback dumps. p95 is nearest rank; small
sample counts are reported, not disguised as a large-population percentile.

| Measurement | One frame per flush | Bounded batched flush |
| --- | ---: | ---: |
| Cold start, one sample | 1,134.981 ms | 1,126.099 ms |
| Warm attach, 10 samples: median / p95 | 5.086 / 5.294 ms | 5.013 / 5.276 ms |
| Quiet probe, 10 samples: median / p95 | 4.874 / 6.461 ms | 3.242 / 3.260 ms |
| Probe during burst: samples | 19 | 35 |
| Probe during burst: median / p95 / max | 93.943 / 279.429 / 279.429 ms | 60.586 / 70.034 / 77.438 ms |
| Full pool pump: p95 / max | 0.145 / 0.849 ms | 0.171 / 0.296 ms |
| Burst completion | 2,317.416 ms | 1,987.652 ms |
| Replica received bytes, including initial snapshot/PTY conversion | 4,299,516 | 8,493,878 |

Raw reports: `results/daemon-single-frame.json`, `results/daemon-batched.json`.
The before variant deliberately restricts the new queue to the first chunk,
reproducing the old writer's one-frame-per-flush behavior. That restriction is
not retained in production. Both final runs use the same active-grid observer.

### Finding and fix

The old transport flushes one frame per pump. Tiny credit frames accumulate
in front of keyboard input, while output bursts can overtake the consumer and
trigger lag repaint even on the fast viewer. The fix separates byte retention
from socket servicing: gather at most 64 KiB into one send batch, preserving
FIFO order and short-send tails. A large single chunk remains zero-copy.

Tests cover 200 ACK-like frames followed by input in one send, partial sends
across chunk boundaries, the 64 KiB cap, zero sends, EAGAIN, and 32 deterministic
varied chunk/short-send partitions. Existing flow-control integrations pass.

A smaller PTY read/parse slice was tried and **reverted** because it did not
improve responsiveness. Profiling did not justify retaining that change.

### Limits still visible

- Cold startup includes the Display pool's one-second reconnect retry delay.
  Warm snapshot attachment does not. Do not claim sub-50 ms cold startup.
- Flooded terminal input remains measurably slower than quiet input. The
  result does not support an under-50 ms flooded-input claim.
- Burst is paced and finite; completion is not maximum PTY/native throughput.
- No keyboard-to-pixel, GPU FPS, long-duration memory soak, WAN behavior or
  daemon-upgrade persistence is established by this benchmark.

## Actual macOS Display, Hub round-trip during output

A separate isolated GUI check uses a private HOME, Hub port 0, own Display
socket and lazily created PTY socket. The finite program writes 5,255,040
payload bytes in paced chunks. Twenty Hub REST-to-Display pings all overlap
that burst, verified by the daemon's output position before completion.

| Hub/Display ping, 20 samples each | median | p95 | max |
| --- | ---: | ---: | ---: |
| Quiet window | 59.021 ms | 62.573 ms | 64.925 ms |
| Terminal burst | 14.928 ms | 15.906 ms | 19.817 ms |

Raw report: `results/window-ping.json`. Active terminal output wakes the render
loop, so the burst run is faster than the quiet idle window. This is evidence
that the Hub/Display control path remains responsive during this particular
burst, **not** that terminal output makes unrelated rendering universally
faster, or that frame/pixel latency equals ping latency.

Screenshots `results/window-cold.png`, `window-burst.png`, `window-resumed.png`
are PID-selected and OCR-checked for the expected program marker. The marker
survives SIGKILL/restart of the actual Display after Hub scene replay. A first
attempt captured too early, before replay; that blank screenshot was rejected
and the procedure corrected. Mere PID persistence is not claimed as repaint
proof.

Run the macOS check with the reviewed capture helper from Lux main (read-only):

```sh
LUX_CAPTURE_SCRIPT=spikes/terminal/capture_macos.py \
  timeout 110 .venv/bin/python -m spikes.terminal.check_daemon_window
```

The helper supplies only its owned test Display PID to the capture tool. It
never stops or reconfigures normal Lux services. Screen Recording permission,
ffmpeg and tesseract are prerequisites. This is a manual live check, not part
of the scoped pytest suite.
