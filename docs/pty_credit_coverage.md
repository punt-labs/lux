# Viewer credit and lag repaint: model and coverage

The window counts payload bytes queued but not yet acknowledged. Snapshot
bytes count too. A receiver returns credit after retaining a fragment in its
bounded assembly buffer; waiting for the whole snapshot would deadlock when
it exceeds one window.

## Model

Fuzz accepts `pty_credit.tex`. With two viewers, ProB checks all **1,024 states
and 5,249 transitions** for both goals:

```sh
timeout 30 fuzz -t docs/pty_credit.tex
timeout 120 probcli docs/pty_credit.tex -model_check \
  -p DEFAULT_SETSIZE 2 -goal '#v.(v:VIEW & available(v)+inflight(v)/=2)'
timeout 120 probcli docs/pty_credit.tex -model_check \
  -p DEFAULT_SETSIZE 2 -goal 'unsafeTail/={}'
```

No violating state is found. The properties are search goals, not state
predicates. Fidelity mutations reproduce both failures:

- Reset available credit while old bytes remain in flight: a subsequent
  repaint creates an extra window of capacity.
- Permit append/send during a dropped-tail repaint: a viewer receives tail
  bytes across a gap without a replacement snapshot.

The model proves finite-state safety, not network fairness or throughput.

## Code and tests

| Partition | Evidence |
| --- | --- |
| Credit and in-flight sum to capacity | Credit-window unit test |
| ACK cannot exceed actual outstanding debt | Invalid-ACK unit test |
| Snapshot larger than the window progresses | 300,000-byte fragment/ACK test |
| Lag reset does not erase old debt | Reset test with 10,000 bytes still in flight |
| Initial snapshot is not restarted by every output burst | Flood-during-partial-snapshot test |
| Close follows final payloads | Ordered exit-frame test |
| Slow viewer does not block fast viewer | Independent-daemon finite 5 MiB burst test |
| Slow viewer catches up by authoritative snapshot | Same burst test waits for SNAPSHOT_START and verifies END |
| Multiple viewers share one process and size | Two production replica pools converge without PID change |
| Passive geometry does not fight active resize | View-sizing policy test |

Wire generation is now version two. It adds SNAPSHOT_START metadata for
repaint/resize resets. Version-one clients must be rejected by hello instead
of silently interpreting the new stream incorrectly.
