# Short lifecycle/resource cycles

This is a bounded local observation, **not** a long-duration soak or a proof
that every workload has no memory/process leaks.

## Procedure

```sh
timeout 90 .venv/bin/python -m spikes.terminal.lifecycle_bench
```

One owned daemon/socket, one persistent control client and production RemotePools:

1. Start a uniquely named program and receive its ready marker.
2. Submit input and observe the program's response, not just PTY local echo.
3. On every third cycle, request exit and wait for retained EXITED state.
4. Close the viewer and attach a new pool to the same session.
5. Verify unchanged PID and retained screen; exited cases do not respawn.
6. Running cases receive a further input/response after reattach.
7. Explicit kill removes the session; listing is empty after each cycle.
8. Repeat 20 times. Observe daemon numeric FDs, RSS and direct children after
   cycles 2, 10 and 20. Observe parent FD count before/after collection too.
9. Close control client, stop/reap the owned daemon, verify socket removal and
   remove the private instance directory.

The new `test_lifecycle_cycles_live.py` also executes five such cycles under the
normal independent-daemon integration fixture. Tests/helpers use hard deadlines
and existing nonblocking ownership/reaping APIs.

## Observed results

macOS 26.6.2 arm64, local Unix socket; raw report `results/lifecycle-cycles.json`.

| Completed cycles | Daemon numeric FDs | Daemon direct children | Daemon RSS |
| --- | ---: | --- | ---: |
| 2 | 6 | none | 58,432 KiB |
| 10 | 6 | none | 58,704 KiB |
| 20 | 6 | none | 58,928 KiB |

The FD set stayed `[0,1,2,3,4,5]`. Parent numeric FD count was 6 before and after
(the same lsof sampling procedure includes measurement pipe descriptors in the
parent). There were no retained sessions or daemon children after the sampled
kill cycles. All 20 PID/screen reattach checks passed, including seven exited
program cases. Final teardown reaped the owner and removed its socket/instance.

RSS rose 496 KiB between warm and final samples; allocators/caches can retain
memory. These three snapshots cannot establish unbounded-run memory behavior.
Native caches, many concurrent terminals, process descendants, interactive
applications, platforms and long-duration/log retention still need review.
Stable runtime lock/log files are intentionally retained in normal use; this
isolated instance is removed after its owner stops.

## Final scheduled validation

Scoped `make check BASE_REF=3712972`: **835 passed, 19 integrations deselected**.
Separately all **19 integration tests pass**. Strict whole-repository typing has
zero errors (seven existing native ImGui source warnings); lint and all quality
ratchets pass, source suppressions remain 123. No test daemon remains. This does
not stand in for the deliberately unrun broader macOS suite.
