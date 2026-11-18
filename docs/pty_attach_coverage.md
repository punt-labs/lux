# Terminal attach: model results and coverage

This is a bounded model of snapshot/tail ordering and viewer detach, not a
proof of the whole daemon. The daemon core is not implemented yet.

## Safety claims

| Claim | Model-check goal (search for a violation) | Result |
| --- | --- | --- |
| A live viewer has exactly its claimed output prefix | `#v.(v:VIEW & phase(v)=live & seen(v)/=1..applied(v))` | No violating state |
| A pending viewer receives no tail before its snapshot completes | `#v.(v:VIEW & phase(v)=pending & seen(v)/={})` | No violating state |
| Viewer detach does not terminate the program | `program=stopped` | No violating state |

Each run visits all **830 states and 4,171 transitions** with two viewers,
three output positions and a two-frame credit limit. The idle operation
represents waiting for IO. Deadlock-freedom with this operation does not prove
that a network peer will eventually return credit or deliver bytes.

## Reproduction

Type-check:

```sh
timeout 30 fuzz -t docs/pty_attach.tex
```

For each goal above:

```sh
timeout 120 probcli docs/pty_attach.tex -model_check \
  -p DEFAULT_SETSIZE 2 -goal 'GOAL_FROM_TABLE'
```

The goals are not included as state predicates. This matters: including them
would prevent the model from reaching a broken state rather than find it.

## Fidelity checks

Both mutations were made in temporary copies, never in the source model.

1. In `CompleteSnapshot`, set the viewer's applied counter to the current
   output position instead of the captured cut. Leave its observed data at
   the captured cut. ProB finds:
   `Init -> CaptureSnapshot -> ReadOutput -> CompleteSnapshot`.
   The viewer claims to have applied bytes that arrived during transfer,
   but its snapshot did not include them.
2. In `Disconnect`, change the program from running to stopped. ProB finds
   a stopped-program state after attach and disconnect. This reproduces the
   original in-Display ownership defect: disconnect kills the shell.

The corrected model finds neither violation.

## Implementation coverage

| Partition | Existing evidence | Status |
| --- | --- | --- |
| Frame fragmentation and bounded buffering | `tests/protocol/test_pty_frames.py` | Covered at codec layer |
| Strict typed hello/attach/list/kill control boundary | `tests/protocol/test_pty_control.py` | Covered at codec layer |
| Both screens, modes and parser continuation in snapshots | `tests/ptyd/test_snapshot.py` | Covered at native codec layer |
| Output arriving between capture and completion | Model and its bad-cut witness | **GAP: core test needed** |
| Credit exhausted, returned, and isolated per viewer | Model only | **GAP: core test needed** |
| Detach and reattach while the program stays live | Model and bad-detach witness | **GAP: real PTY integration needed** |
| Socket peer authentication and stale endpoint handling | Outside this model | **GAP: service implementation and tests needed** |
| Explicit session kill and daemon shutdown | Outside this model | **GAP: lifecycle model and tests needed** |

These gaps must be filled as the implementation reaches each stage. Passing
codec tests is not evidence that socket or process lifecycle works.
