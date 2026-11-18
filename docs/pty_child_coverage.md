# PTY child ownership: model and implementation coverage

The parent is the sole waiter for each child. No other thread or component may
call `waitpid` for it. Kernel exit may interleave with parent IO; reaping
releases the PID, and signalling after that could target a reused PID.

## Model results

`docs/pty_child.tex` type-checks with Fuzz. Both safety checks visit all
**28 states and 75 transitions**:

```sh
timeout 30 fuzz -t docs/pty_child.tex
timeout 120 probcli docs/pty_child.tex -model_check -goal 'gone:signals'
timeout 120 probcli docs/pty_child.tex -model_check \
  -goal 'tracked=no & life/=gone'
```

No violating state is found. Safety properties are search goals, not state
predicates that prevent the bad states from being reached.

Fidelity mutations, in temporary copies:

- Removing the reap guard from `SignalChild` yields
  `Init -> KernelExit -> SignalChild -> PollReap -> SignalChild`.
  The second signal targets a released PID.
- Removing the reap guard from `ForgetChild` yields
  `Init -> KernelExit -> ForgetChild`.
  A zombie child is forgotten before the parent reaps it.

The fixed model finds neither violation. It does not prove scheduling or
kernel response deadlines, nor cleanup of deliberately detached grandchildren.

## Code and tests

| Partition | Implementation | Evidence |
| --- | --- | --- |
| Short writes and EAGAIN retain input | `InputBuffer.flush` | Exact-order unit test plus 20,000-byte real-PTY input test |
| Input overflow does not discard earlier bytes | `InputBuffer.append` | Bounded-buffer unit test |
| Reaping is always nonblocking | `ChildLifetime.poll` | WNOHANG assertion and live exit-status tests |
| Reaped PID is never signalled | `ChildLifetime.stop` | Unit test fails if `os.kill` is called after reap |
| Master descriptor is closed once | `PtyHolder.close` | Repeated-close integration test |
| Exec failure cannot return into parent Python | `PtyHolder._exec_child` | Missing-executable test sees status 127 |
| Failed close keeps session ownership | `SessionCore.kill` | Retry and multi-session shutdown tests |
| Failed terminal construction and close retain the process | `SessionCore.acquire` | Injected allocation/close failure preserves both errors and pending ownership |
| Authoritative state stays current without viewers | `TerminalSession.pump` | Fake-process and real headless-core tests |
| Snapshot cut followed by output has no gap | `TerminalSession.capture` | Restore captured bytes, then apply later output and compare screen |
| Automatic query replies have one owner | `TerminalSession` | One reply from the core; decoding the snapshot emits no duplicate |
| Parser callback failure cannot advertise a false cut | `TerminalSession.pump` | Failed state rejects subsequent capture |

Later peer/daemon/credit models and integrations cover socket authentication,
attach/disconnect, idle exit and stale endpoint recovery. Actual-window evidence
covers Display SIGKILL/restart with the same program and visible marker.
Daemon crash recovery only reclaims the endpoint; it does not preserve programs.
These are complementary observations, not additional claims proved by this
child model. Native/OS soak, other platforms and full pixel fidelity remain gaps;
see spikes/terminal/STEP4-REVIEW.md.
