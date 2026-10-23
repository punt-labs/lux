# Listener lifecycle: test partitions and coverage

Companion to [listener_lifecycle.tex](./listener_lifecycle.tex), the model of the
Hub display link's reader thread, its socket, its reply sinks and the request that
waits on a sink. The model checks six invariants (L1 to L6, with L4 in two parts)
and deadlock-freedom; this note derives the test partitions the model implies and
records which existing tests cover them. Gaps are marked **GAP**. The fixed design
has not been implemented, so *covered* means the test exercises the behaviour the
model keeps, and *covered (current code)* means the test passes today for a reason
the fix must preserve.

## The model, in one paragraph

A dial makes a generation. A reader is started on a generation, may be stopped and
joined, or stopped and abandoned (join timed out). A reader with permission routes
a reply into the sink of its own generation, or reports its stream broken by
compare-and-close on its own generation. The link closes a generation deliberately.
A caller writes a request (`Send`, which returns the generation), then waits on
that generation's sink (`Await`); a timeout ends the generation. Test partitions
follow the operations and the guards that choose between their outcomes.

## The invariants

| Id | Statement |
|---|---|
| L1 | queued replies lie in the live current generation's sink; a waiting caller waits on the live generation it wrote to |
| L2 | a generation is closed only by the link (or the caller's timeout) or by its own reader |
| L3 | a stopped reader takes at most one routing or reporting step after its flag is set |
| L4a | at most one reader per live generation |
| L4b | a reader holds only its own generation's bytes (it never reads through `require()`) |
| L5 | no caller consumes a reply of another generation |
| L6 | no caller consumes the reply to an earlier request |

## Verification record

Commands run from `docs/`. `probcli` is `/home/jfreeman/Applications/ProB/probcli`;
every call passes `-p DEFAULT_SETSIZE 2 -p MAX_OPERATIONS 200`. The z-spec MCP tools
decline in this repository ("z-spec is not enabled here"), so `fuzz` and `probcli`
were run directly. Goals were run with `-model_check -nodead -bf -goal "<negation>"`;
the negations are listed in the specification's Verification section.

| Check | Result |
|---|---|
| `fuzz` on the fixed spec and the four controls | clean (no output, exit 0) |
| `-model_check -coverage` (deadlock detection on), fixed | 66200 states analysed, 233638 transitions, no counter example, `deadlocked:0`, `UNCOVERED_OPERATIONS (0)` (all 18 operations, incl. `Send`, `Await`, `AwaitFail`, `Consume`, `TimeoutRetire`) |
| `-model_check -nodead -coverage`, `_current_buggy` | 403014 states, 1446272 transitions, 0 uncovered operations |
| the same, `_production_buggy` | 170605 states, 535816 transitions, 0 uncovered |
| the same, `_gate_only_buggy` | 281329 states, 1036446 transitions, 0 uncovered |
| the same, `_stale_reply_buggy` | 110012 states, 401516 transitions, 0 uncovered |

Negated-invariant searches (breadth-first, so the traces are shortest). "not found"
means the whole reachable space was visited.

| Spec | L1 (L1q queue, L1w waiter) | L2 | L3 | L4a | L4b | L5 | L6 |
|---|---|---|---|---|---|---|---|
| fixed (66200 states) | not found (both) | not found | not found | not found | not found | not found | not found |
| `_current_buggy` | **found** (both) | **found** | **found** | **found** | **found** | **found** | **found** |
| `_production_buggy` | **found** (both) | **found** | **found** | not found (170605 states) | **found** | **found** | **found** |
| `_gate_only_buggy` | **found** (both) | **found** | not found (281329 states) | **found** | not found | **found** | **found** |
| `_stale_reply_buggy` | not found (110012 states) | not found | not found | not found | not found | not found | **found** |

Shortest traces. The `_current_buggy` rows admit paths the production callers do
not take (a close that does not follow a stop; a start over an unjoined reader on
an open socket), so the production control is the one that speaks for the code as
it ships. Public-API traces are labelled as such.

| Defect | Spec | Trace |
|---|---|---|
| R3-1 (L2) | `_production_buggy` | `Dial; StartListener(ta); StopTimeout(ta); Close; Dial; BrokenWrong(ta)` |
| R3-1 (L2), public API | `_current_buggy` | `Dial; StartListener(ta); Close; Dial; BrokenWrong(ta)` (a close with no stop) |
| SF3-2 (L1q) | `_production_buggy` | `Dial; StartListener(ta); StopTimeout(ta); Send; FeedCurrent(1,ta); Close; RouteShared(1,ta)` |
| SF3-2 misdelivery (L5) | `_production_buggy` | `Dial; StartListener(ta); Send; AwaitShared; StopTimeout(ta); FeedCurrent(1,ta); Close; Dial; Send; RouteShared(1,ta); AwaitShared; ConsumeAny` |
| redial between send and wait (L1w) | `_production_buggy` | `Dial; Send; Close; Dial; AwaitShared` |
| two readers on a socket, production (L4b) | `_production_buggy` | `Dial; StartListener(ta); StopTimeout(ta); Close; Dial; Send; FeedCurrent(1,ta)` |
| two readers on a socket, public API (L4a) | `_current_buggy`, `_gate_only_buggy` | `Dial; StartListener(ta); StopTimeout(ta); StartListener(tb)` |
| step after stop (L3) | `_production_buggy` | `Dial; StartListener(ta); StopTimeout(ta); Send; FeedCurrent(1,ta); RouteShared(1,ta); BrokenOwn(ta)` |
| flag-only repair still fails (L2) | `_gate_only_buggy` | `Dial; StartListener(ta); CheckPermit(ta); StopTimeout(ta); Close; Dial; BrokenWrong(ta)` |
| flag-only repair still fails (L1q) | `_gate_only_buggy` | `Dial; StartListener(ta); CheckPermit(ta); Send; Feed(1,ta); StopTimeout(ta); Close; RouteShared(1,ta)` |
| late reply to an earlier request (L6) | `_stale_reply_buggy` | `Dial; StartListener(ta); Send; Await; Feed(1,ta); TimeoutPlain; CheckPermit(ta); RouteLive(1,ta); Send; Await; Consume` |

Reachability on the fixed spec (each **found**, so the invariants are not vacuous):
`afterStop(ta) = 1` (`Dial; StartListener(ta); CheckPermit(ta); StopTimeout(ta);
BrokenOwn(ta)`: the one step a stopped reader may still take), an abandoned reader
with a running successor, `qrep /= {}`, `broken /= {}`, `cstate = cwait`, and a
request that times out followed by a redial and a second request.

What the evaluation changed in this revision, for the record: L3 was vacuous (a
history flag nothing set) and is now a step counter whose permitted value is
reached; `Request` was one atomic step and is now `Send` then `Await`; the control
for the code now reads through `require()`; the stopping-flag control no longer
keeps the fixed design's fourth `StartListener` guard; L5 and L6 are new.

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
| S7 | start over an unjoined reader first retires that reader's generation (L4a) | StartListener guard 4 | none | **GAP** |
| S8 | the abandoned reader exits at its next stopping test | ExitStopped | same test as S5/S6 (second Pong routed by the new thread) | covered |

### Routing (CheckPermit, Feed, RouteLive, RouteDead)

| # | Partition | Model operation | Existing test | Status |
|---|---|---|---|---|
| R1 | a reader routes each decoded message as it is decoded | RouteLive | `TestRouting::test_every_decoded_message_is_routed`, `test_a_frame_split_across_reads_is_routed_once_complete` | covered |
| R2 | a raising route costs its message, not the reader | RouteLive, error edge | `TestARaisingRoute` | covered |
| R3 | a reply is queued in the sink of the reader's own, live generation | RouteLive | `test_inbound_router.py` (ack, pong, query kept apart) tests the queue, not the generation | **GAP**: no test asserts the sink belongs to a generation |
| R4 | a reply from a retired generation is dropped, not queued (L1) | RouteDead | none | **GAP** |
| R5 | a reader whose flag is set takes at most one more routing or reporting step, the one it held permission for; with no permission it takes none (L3) | CheckPermit guard, `afterStop <= 1` | none | **GAP**. Two tests: (a) set the flag with no permission outstanding, release the reader's handler: no further route, no report; (b) set the flag after the permission was taken: exactly one step, and it lands in the reader's own generation's sink |
| R6 | the one permitted step after stop is confined: it cannot reach the replacement (L1, L2) | RouteLive or BrokenOwn after StopTimeout | none | **GAP**. Test: stop (times out), redial, then let the permitted step run; the replacement's sink and socket are untouched. This is the test that stands in for "the flag is hygiene, not safety" |
| R7 | a waiter on the new generation is never answered by an old generation's reply (L5, SF3-2 symptom) | Consume after RouteDead | none | **GAP** |
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
| B8 | the replacement's waiter survives a stale report | BrokenStale leaves the connection unchanged | none | **GAP** |

### Closing, redialing and the request (Dial, Close, Send, Await, AwaitFail, Consume, TimeoutRetire)

| # | Partition | Model operation | Existing test | Status |
|---|---|---|---|---|
| C1 | open dials; open on an open connection is a no-op | Dial guard | `test_display_connection.py` (open tests) | covered |
| C2 | a failed dial leaves the connection closed | Dial, error edge | `test_display_connection.py::test_a_dial_that_fails_leaves_the_connection_closed` | covered |
| C3 | closing a closed connection is not an error | Close, idempotent | `test_display_connection.py::test_closing_a_closed_connection_is_not_an_error` | covered |
| C4 | closing discards queued replies and fails waiters | Close | `test_inbound_router.py::test_reset_discards_replies_a_dying_listener_left`, `test_a_listener_that_exited_fails_the_waiter_instead_of_timing_out` | covered |
| C5 | a redial carries no reply and no waiter of the generation before | Dial | none that asserts it across a close and redial | **GAP** |
| F7 | a request that times out ends its generation; the next request, on the redialed generation, is never handed the earlier request's late reply (L6) | TimeoutRetire; the stale-reply control | none | **GAP**. Test: send a ping to a display that answers after the budget; the caller times out and the connection closes; the late pong, if it arrives at all, is dropped; the next ping is answered only by its own pong. Also the request lock: two threads sending at once are serialised (one in flight per link) |
| T1 | a request sent on generation g is answered only from g; a redial between send and wait fails the waiter, never consuming g+1's reply (Decision 4, L1w, L5) | Send; AwaitFail | none | **GAP**. `send` must return the generation; test by redialing in a seam between the send and the wait |
| T2 | a waiter on g fails promptly when g is closed or g's reader exits, even while an abandoned reader of g-1 is alive (Decision 6) | Close, BrokenOwn, TimeoutRetire fail the waiter; promptness is a liveness property the model does not check | none (`test_a_pending_reply_fails_when_the_listener_exits` covers the link-level listener only) | **GAP** |

### Socket and thread realization

| # | Partition | Model operation | Existing test | Status |
|---|---|---|---|---|
| T3 | an abandoned reader never reads the replacement's socket (L4b, the production route to two readers) | Feed guard `lgen = curGen` | none | **GAP**: stall a reader past the join after it passed `is_open`, redial, release it; assert it read nothing from the new socket, and that `poll_chunk` is not reaching `require()` |
| T4 | `shutdown(SHUT_RDWR)` before `close()` releases a sender wedged in `sendall` and a reader blocked on `_lock` behind it (Decision 3) | the realization of StartListener guard 4 | none | **GAP**; pairs with row D |
| T5 | the business-event policy: closing a generation does not drain the link-level event queue; events queued before a close and events a straggler routes after it are both delivered; interaction handlers may run on two threads, out of order (Decision 7) | none (outside L1 by design) | `test_inbound_router.py::test_reset_discards_events_queued_before_it` asserts the opposite and must change with the fix | **GAP**, and an existing test to rewrite |

### Invariants and deadlock

| # | Property | Existing test | Status |
|---|---|---|---|
| L1 | replies and the waiter stay within the live generation | none | **GAP** (R3, R4, R7, R8, T1) |
| L2 | a generation is closed only by the link, the caller's timeout, or its own reader | none | **GAP** (B5, B6) |
| L3 | a stopped reader takes at most one step | none | **GAP** (R5, R6) |
| L4a | one reader per live generation | none | **GAP** (S7) |
| L4b | a reader holds only its own generation's bytes | none | **GAP** (T3) |
| L5, L6 | no wrong reply is consumed | none | **GAP** (R7, T1, F7) |
| D | the lock graph: request lock, then state lock, then a queue lock, with `_lock` a leaf; a report never takes the request lock and never `_lock` | `test_single_writer.py` covers the single-writer discipline for the replicator, not these locks | **GAP**: assert the state lock is not `_lock`, and that a report from another thread still closes the generation while a sender is blocked in `sendall` on a wedged peer |

## What the implementation mission must add

The gaps S7, R3 to R8, B5 to B8, C5, F7, T1 to T5 and D are the regression tests of
the design, and each fails against today's code. B5 is the test named in the R3-1
review. R8 is the SF3-2 review's test. Neither is sufficient alone: the
stopping-flag control passes both and still violates L1 and L2 across the window
between the test and the act. The tests that distinguish the design from that
repair are R4, R6, R7 and B7: they hold the reader between its look and its step,
then replace the connection.

One existing test asserts behaviour the design reverses (T5,
`test_reset_discards_events_queued_before_it`); it is rewritten with the fix, not
deleted. F7 is a behaviour change for callers, not only an internal one: a request
that times out now costs the connection. The leader should weigh that before the
implementation mission is cut.

Re-run `fuzz` and the model-check, and revisit this table, whenever the reader,
the connection or the reply queues change how a reader is started, stopped or
allowed to act, or how a request is sent and awaited.
