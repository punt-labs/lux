# Listener lifecycle: test partitions and coverage

Companion to [listener_lifecycle.tex](./listener_lifecycle.tex), the model of the
Hub display link's reader thread, its socket and its reply sinks. The model
checks four invariants (L1 to L4) and deadlock-freedom; this note derives the
test partitions the model implies and records which existing tests cover them.
Gaps are marked **GAP**. The fixed design has not been implemented, so a row
marked *covered* means the test exercises the behaviour the model keeps, and
a row marked *covered (current code)* means the test passes today for a reason
the fix must preserve.

## The model, in one paragraph

A dial makes a generation. A reader is started on a generation, may be stopped
and joined, or stopped and abandoned (join timed out). A reader with permission
routes a reply into the sink of its own generation or reports its stream broken
by compare-and-close on its own generation. The link closes a generation
deliberately. Test partitions follow the operations and the guards that choose
between their outcomes.

## Verification record

Commands run from the repository root. `probcli` is
`/home/jfreeman/Applications/ProB/probcli`. Every call below also passes
`-p DEFAULT_SETSIZE 2 -p MAX_OPERATIONS 200`.

| Check | Spec | Result |
|---|---|---|
| `fuzz docs/listener_lifecycle.tex` | fixed | clean (no output) |
| `fuzz` on both controls | controls | clean |
| `-model_check` (deadlock on) | fixed | 7531 states, 32267 transitions, no counter example, all states visited; `-coverage`: 17 of 17 operations covered, 0 deadlocked |
| `-model_check` with maxGen 4, maxBuf 2 (scratch copy) | fixed | 52322 states, 235256 transitions, no counter example |
| `-goal` L1 negation | fixed | not found |
| `-goal` L2 negation | fixed | not found |
| `-goal` L3 negation (`leak = fset`) | fixed | not found |
| `-goal` L4 negation | fixed | not found |
| the four goals in one disjunction, maxGen 4 | fixed, scratch copy | not found |
| `-goal "qgen /= {}"`, `"broken /= {}"`, abandoned reader with running successor, abandoned reader with buffered frames | fixed | each found (the invariants are not vacuous) |
| L2 negation | `_current_buggy` | **found**, 10-step trace ending `BrokenWrong(tb)` |
| L1 negation | `_current_buggy` | **found**, `Dial, StartListener(ta), Feed(ta), Close, RouteShared(ta)` |
| L3 negation | `_current_buggy` | **found**, `Dial, StartListener(ta), StopTimeout(ta), BrokenOwn(ta)` |
| L4 negation | `_current_buggy` | **found**, `Dial, StartListener(tb), Request, StopTimeout(tb), StartListener(ta)` |
| L2 negation | `_gate_only_buggy` | **found**, `Dial, StartListener(ta), CheckPermit(ta), Close, StopTimeout(ta), Dial, BrokenWrong(ta)` |
| L1 negation | `_gate_only_buggy` | **found**, `Dial, StartListener(ta), Feed(ta), Close, CheckPermit(ta), RouteShared(ta)` |
| L3, L4 negations | `_gate_only_buggy` | not found (16115 states) |

The first run of the fixed spec reported three operations uncovered
(`RouteLive`, `BrokenOwn`, `Consume`): a frame-condition error in the spec
itself, found by `-coverage` and corrected. A model-check that prints "no
counter example" without that coverage line is not evidence.

## Partitions

Each partition is a class of behaviour the model distinguishes. Tests live in
`tests/domain/` unless a path says otherwise.

### Starting and stopping (StartListener, StopJoined, StopTimeout, ExitStopped)

| # | Partition | Model operation | Existing test | Status |
|---|---|---|---|---|
| S1 | start on an open connection runs a reader | StartListener | `test_listener_thread.py::TestLifecycle` (start, idempotent start) | covered |
| S2 | start while a reader runs and is not stopping is a no-op | StartListener guard 3 | `TestAbandonedThread::test_start_while_running_and_not_stopping_changes_nothing` | covered |
| S3 | stop joins and forgets the thread | StopJoined | `TestLifecycle::test_stop_joins_the_thread_and_forgets_it` | covered |
| S4 | stop never started is not an error | none (boundary) | `TestLifecycle::test_stopping_a_listener_never_started_is_not_an_error` | covered |
| S5 | stop times out; the thread lives, told to stop | StopTimeout | `TestAbandonedThread::test_start_replaces_a_thread_stop_could_not_join` | covered |
| S6 | start abandons the unjoined thread and runs a new one | StartListener over an `lstop` reader | same test | covered (current code); the fixed design changes it, see S7 |
| S7 | start over an unjoined reader first retires that reader's generation (L4) | StartListener guard 4 | none | **GAP** |
| S8 | the abandoned reader exits at its next stopping test | ExitStopped | same test as S5/S6 (second Pong routed by the new thread) | covered |

### Routing (CheckPermit, Feed, RouteLive, RouteDead)

| # | Partition | Model operation | Existing test | Status |
|---|---|---|---|---|
| R1 | a reader routes each decoded message as it is decoded | RouteLive | `TestRouting::test_every_decoded_message_is_routed`, `test_a_frame_split_across_reads_is_routed_once_complete` | covered |
| R2 | a raising route costs its message, not the reader | RouteLive, error edge | `TestARaisingRoute` | covered |
| R3 | a reply is queued in the sink of the reader's own, live generation | RouteLive | `test_inbound_router.py` (ack, pong, query kept apart) tests the queue, not the generation | **GAP**: no test asserts the sink belongs to a generation |
| R4 | a reply from a retired generation is dropped, not queued (L1) | RouteDead | none | **GAP** |
| R5 | a stopped reader holding no permission routes nothing (L3) | CheckPermit guard | none | **GAP** |
| R6 | a reader stopped after its permission may take that one step and no more | RouteLive after StopTimeout | none | **GAP** (note: this is the one place the model admits a stopped reader acts; its effect is confined by R4) |
| R7 | a waiter on the new generation is never answered by an old generation's reply (L1, SF3-2 symptom) | Consume after RouteDead | none | **GAP** |
| R8 | blocked route on message k of a chunk, stop times out, successor started, route released: message k+1 is not routed | RouteDead, buffered | none (the review's proposed test) | **GAP** |

### Reporting (BrokenOwn, BrokenStale)

| # | Partition | Model operation | Existing test | Status |
|---|---|---|---|---|
| B1 | a read failure on the reader's own open generation closes it and is reported | BrokenOwn | `TestTellingTheLink::test_a_read_failure_on_an_open_connection_is_a_warning_and_reported` | covered |
| B2 | a display that closes the stream: reported, link closes | BrokenOwn | `TestTellingTheLink::test_a_display_that_closes_the_stream_is_reported_and_the_link_closes`; `test_display_link.py::test_a_pending_reply_fails_when_the_listener_exits` | covered |
| B3 | a malformed frame: reported, connection closed on a frame boundary | BrokenOwn | `TestMalformedFrames`, `TestTellingTheLink::test_a_malformed_frame_is_reported_to_the_link`, `test_display_link.py::test_an_unknown_message_type_ends_the_connection` | covered |
| B4 | a deliberate close is not a break and is not reported | BrokenStale (generation closed) | `TestTellingTheLink::test_a_deliberate_close_is_debug_and_not_reported`; `TestLifecycle::test_exits_when_the_connection_is_closed_under_it` | covered |
| B5 | a reader of a retired generation whose read fails while a healthy replacement is open reports nothing and closes nothing (L2, R3-1) | BrokenStale, replacement held | none | **GAP**: the central regression test |
| B6 | the same with a malformed frame in the retired reader's buffer (SF3-2, second half) | BrokenStale after Feed | none | **GAP** |
| B7 | the report is atomic with the dial's publication (no interleaving closes a generation dialed after the check) | the state-lock requirement | none; unreachable by a deterministic test without a seam | **GAP**: needs a hook between the generation check and the close, or a stress test marked `slow` |
| B8 | the replacement's pending waiters survive a stale report | BrokenStale leaves Conn unchanged | none | **GAP** |

### Closing and redialing (Dial, Close, Request, Consume)

| # | Partition | Model operation | Existing test | Status |
|---|---|---|---|---|
| C1 | open dials; open on an open connection is a no-op | Dial guard | `test_display_connection.py` (open tests) | covered |
| C2 | a failed dial leaves the connection closed | Dial, error edge | `test_display_connection.py::test_a_dial_that_fails_leaves_the_connection_closed` | covered |
| C3 | closing a closed connection is not an error | Close, idempotent | `test_display_connection.py::test_closing_a_closed_connection_is_not_an_error` | covered |
| C4 | closing discards queued replies and fails waiters | Close | `test_inbound_router.py::test_reset_discards_replies_a_dying_listener_left`, `test_a_listener_that_exited_fails_the_waiter_instead_of_timing_out` | covered |
| C5 | a redial carries no reply and no waiter of the generation before | Dial | none that asserts it across a close and redial | **GAP** |

### Invariants and deadlock

| # | Property | Existing test | Status |
|---|---|---|---|
| L1 | replies and waiters stay within the live generation | none | **GAP** (R3, R4, R7, R8) |
| L2 | a generation is closed only by the link or its own reader | none | **GAP** (B5, B6) |
| L3 | a stopped reader without permission is silent | none | **GAP** (R5) |
| L4 | one reader per live generation | none | **GAP** (S7) |
| D | no lock nesting: the report takes the state lock only; the sender holds `_lock` only across a send; the router holds a queue lock only across a put or get | `test_single_writer.py` covers the single-writer discipline for the replicator, not these locks | **GAP**: assert the state lock is not `_lock` and that the report does not block behind a stuck `sendall` (a sender blocked in `sendall` on a wedged peer; the report from another thread still closes the generation) |

## What the implementation mission must add

The gaps S7, R3 to R8, B5 to B8, C5 and D are the regression tests of the
design, and each fails against today's code. B5 is the test named in the R3-1
review ("start a listener, set its stopping event, swap in a new open
connection, then make the old read fail; `on_broken` must not fire and the
new connection must stay open"). R8 is the SF3-2 review's test. Neither is
sufficient alone: the gate-only control shows the flag-test fix passes both
and still violates L1 and L2 across the window between the test and the act.
The tests that distinguish the design from the gate-only repair are R4, R7
and B7: they hold the reader between its look and its step, then replace the
connection.

Re-run `fuzz` and the model-check, and revisit this table, whenever the
reader, the connection or the reply queues change how a reader is started,
stopped or allowed to act.
