# Listener lifecycle: test partitions and coverage

Companion to [listener_lifecycle.tex](./listener_lifecycle.tex), the model of the
Hub display link's reader thread, its socket, its reply sinks and the requests that
wait on a sink. The model checks eleven invariants (L1 to L11, with L1 and L4 in two
parts) and deadlock-freedom; this note derives the test partitions the model
implies and records which existing tests cover them. Gaps are marked **GAP**. The
fixed design has not been implemented, so *covered* means the test exercises the
behaviour the model keeps, and *covered (current code)* means the test passes today
for a reason the fix must preserve.

Governing ADRs: DES-093 (the Hub never controls the display's process; pacing,
backoff and the manifest reconcile belong to the registry), DES-090 (the cross-host
dialer is per dial, so the generation sits above the transport), DES-101 (a
lifecycle step is one operation under one lock).

## The model, in one paragraph

A dial makes a generation. A reader is started on a generation, once. Stopping it,
joined or abandoned, closes the generation. A reader with permission routes a reply
into the sink of its own generation, or reports its stream broken by
compare-and-close on its own generation. The link closes a generation
deliberately. A caller wants a kind of request (ping, scene, query), takes that
kind's request lock, writes (`Send`, which returns the generation), then waits on
that generation's sink (`Await`). The replicator also writes scenes nobody waits
for (`SendNoWait`). An arriving reply is delivered to the waiter it matches (a pong
by its `ts`, an ack by its position among the acks owed) and dropped otherwise; a
query that times out ends its generation, a ping or scene that times out does not,
and a budget that runs out waiting for the lock sends nothing and ends nothing. A display that cannot send a reply closes the connection (`Sever`); it never drops a reply on a live one.
Test partitions follow the operations and the guards that choose between their
outcomes.

## Errata to the previous revision

The round-2 revision of this note and of the specification said that retiring a
generation on any request's timeout needed "no wire change and no assumption about
the display". That was wrong: it assumed every write that elicits a reply is awaited
(the replicator's `send_scene` is not; `listener_lifecycle_nowait_buggy.tex`
reproduces the defect with no timeout at all), it assumed the display answers at
most once, and its one-caller model hid the lock-wait case. Decision 5 of the
specification is rewritten; rows F7, F7a, F7b, F7c, S9, M1 to M4, W1 to W3 and T6 below are
new or changed. The round-2 rows are otherwise unchanged.

A second errata, from the second round: assumption A1 (one ack per scene, none lost
on a live connection) is false of the display as shipped. `_handle_scene` discards the
result of `send_to_client`, which returns `False` when a send cannot complete before the
frame deadline, leaves the client connected, and nothing resends. The ruling: the display
never drops a reply on a live connection; when it cannot send one it closes that
connection and the Hub redials (the model's `Sever`; `_lose` is the display as
shipped). Three Hub-side failure-path rules (rows W1 to W3) and the mandatory `scene_id`
cross-check (row M4) follow.

A third errata, round 4 (mission m-2026-10-25-003). The specification said that
`Close` was "the link closing the connection on purpose" and gave it no argument,
and treated a retirement as one atomic step. Both were wrong of the code, and the
model could not see the two defects that follow from them (final review, silent
finding 2 and invariant finding F5): a caller's `drop()` after its own dial failed
closed whatever dial was current, a successor included; and `close_if_current`
marks the generation closed under the state lock and discards the sink only in
`shut`, so a reader mid-chunk could still deliver in between. The connection is now
three-valued (`hclear`, `hlive`, `hretiring`); `Close` carries the generation its
caller holds and acts only on the current live one (R1); `Teardown` is the second
step, and delivery requires `hlive` (R7). L1 and L2 are restated for the window
(table below); L10 and L11 are new. Rows X1 to X8 are new. Neither ruling is
unsound in the model: both hold at the existing bounds, and each control
reproduces its defect.

## The invariants

| Id | Statement |
|---|---|
| L1 | parked replies lie in the current generation's sink (live, or retiring with the sink not yet discarded); a waiting caller waits on the current generation it wrote to |
| L2 | a generation is not live (closed or retiring) only because the link closed it (as the generation it holds), a stop, a query's timeout, the display, or its own reader |
| L3 | a stopped reader takes at most one routing or reporting step after its flag is set |
| L4a | at most one reader per live generation |
| L4b | a reader holds only its own generation's bytes (it never reads through `require()`) |
| L5 | no caller consumes a reply of another generation |
| L6 | no caller consumes the reply to an earlier request |
| L7 | a lock-wait expiry never retires a generation (it sent nothing) |
| L8 | a liveness ping's lock wait is not held up by another kind of request |
| L9 | the sink is bounded: no reply is parked for a caller that is not waiting |
| L10 | no successor is closed by a predecessor's failure: `drop(g)` closes only if `g` is the current, live generation (ruling R1) |
| L11 | a retired generation parks no reply: the dial reads as closed only in the one sink-lock hold that discards its sink, so no reply is parked for a waiter once the dial reads closed. An interaction already routed or held is the link's and still runs (ruling R7) |

L7 and L8 are tautologies of the fixed specification: no fixed operation writes
`wrongRetire` or `starved`, so their goals are not a search. Their content is in the
guards of `Send` and `LockExpire`, and the controls (`_lock_expiry`, `_perlink_lock`) are
their evidence. The model's deadlock check is likewise trivial (`Want` is enabled for
every idle caller, `LockExpire` for every caller waiting for a lock); the lock order is
argued, and its model-checked companion (`docs/listener_locks.tex`, with an inverted
control) is to come.

## Verification record

Commands run from the repository root on scratch copies of the files under `docs/`
(so that `probcli` wrote no `.fuzz` files beside them). `probcli` is
`/home/jfreeman/Applications/ProB/probcli`. The z-spec MCP tools decline in this
repository ("z-spec is not enabled here"), so `fuzz` and `probcli` were run
directly. `T` (readers) and `C` (callers) are given sets, sized with `-card`.

**One finding about the method.** An invariant written in the state schema of a Z
specification is not checked by ProB: the primed state schema is part of every
operation's guard, so an operation whose result would violate it is *disabled*. A
control that plainly violates `crossReq = fclear` then reports the goal `crossReq =
fset` "not found" over the whole space. The invariants are therefore searched as
negated goals, never written into the schema. (With them written in, the smallest
shape of the fixed design took the same 815678 transitions as without (before `Sever` was added), so nothing
was pruned there; this was checked, not assumed.)

```text
fuzz docs/listener_lifecycle.tex and the 18 control files          exit 0, no output
                                   (round 4: the fixed file and the two new controls
                                    re-run separately, each exit 0)

goal ALL = the disjunction of the negations of L1q, L1w, L2, L3, L4a, L4b, L5, L6,
           L7, L8, L9, L10, L11 (every invariant at once; deadlock detection on),
           in the form of the round-4 goal file:
           (mbox /= {} & (held = hclear or #c.(c:dom(mbox) & rgen(mbox(c)) /= curGen)))
           or #c.(c:C & cstate(c) = cwait & (held = hclear or rgen(creq(c)) /= curGen))
           or (held /= hlive & curGen > 0 & curGen /: (broken \/ deliberate))
           or #t.(t:T & afterStop(t) > 1)
           or #(t,u).(t:T & u:T & t /= u & lst(t) /= lexit & lst(u) /= lexit & lgen(t) = lgen(u))
           or #t.(t:T & {r | r:bufr(t) & rgen(r) /= lgen(t)} /= {})
           or crossGen = fset or crossReq = fset or wrongRetire = fset or starved = fset
           or #c.(c:dom(mbox) & cstate(c) /: {csent,cwait})
           or wrongDrop = fset or lateDeliver = fset

probcli listener_lifecycle.tex -model_check -coverage -goal "<ALL>" \
  -p MAX_OPERATIONS 200 -card T 1 -card C 1    -> 541155 states, 3789531 transitions, no counter example, ALL states visited,
                                                  deadlocked:0, UNCOVERED_OPERATIONS (0) of 32  (6 min, 1.9 GB)
probcli listener_lifecycle.tex -model_check -coverage -goal "<ALL>" \
  -p MAX_OPERATIONS 200 -card T 2 -card C 1    -> 4950738 states, 37922025 transitions, no counter example, ALL states visited,
                                                  deadlocked:0, UNCOVERED_OPERATIONS (0) of 32  (90 min, 16 GB)
probcli listener_lifecycle_g2.tex -model_check -coverage -goal "<ALL>" \
  -p MAX_OPERATIONS 200 -card T 1 -card C 2    -> 2072834 states, 16691681 transitions, no counter example, ALL states visited,
                                                  deadlocked:0, UNCOVERED_OPERATIONS (0) of 32  (about 25 min, 8 GB)
```

**The bounds, per invariant (round 4).** The first two runs are at the existing
bounds (`maxGen` = 3, `maxReq` = 2, `maxBuf` = 1). The third, one reader with two
callers, is at **`maxGen` = 2**: `listener_lifecycle_g2.tex` is
`listener_lifecycle.tex` with the one line `maxGen = 3` changed to `maxGen = 2`
(a scratch copy, not committed). The three-generation run (`-card T 1 -card C 2`) grew
the state space past 8.3 million states and 28 GB at 86% and was stopped, on the
coordinator's instruction, because the machine has 30 GB; it had found no
counter example up to that point (7.16 million states checked). Why 2 is enough
for that shape: that shape speaks for L7, L8 and the per-kind request locks, whose
control traces are five steps on one generation; for L10, whose trace needs two
generations and no more; and for L11, which needs one. Every invariant that needs a
third generation (an abandoned reader of the first against a replacement of the
second, itself replaced) is exercised by the `-card T 2 -card C 1` run at three
generations. The fixed design therefore holds at three generations for one caller
with two readers, at two generations for two callers with one reader, and at three
generations for one reader and one caller. Each fidelity control reproduces its
trace at both `maxGen` values and in both `-card` shapes (the C2 shape finds
`_retire_split` by a different eight-step trace of the same defect, the
`CheckPermit` before the `Close`: 8915 states), so the reduced bound still
exposes the defect.

The product of two readers and two callers was started and abandoned: a control run
in that shape estimated over two million states at under half the search, at about
800 states a second, and did not finish in 25 minutes. Every new operation touches either the reader state or the caller
state, and they meet only in the sink, which both shapes contain; the two shapes
together cover both sides of it. They are different questions: the first holds two
readers (an abandoned one and its successor) against one caller, so it speaks for
L1 to L6 and L9 under stale readers; the second holds two callers against one
reader, so it speaks for L7, L8 and the per-kind locks. **Three reader slots.** The
evaluator's check of the round-2 revision with `T` of three (one caller, 752902
states, 2930922 transitions, `deadlocked:0`, 0 uncovered) found every invariant
preserved, and the double abandonment `Dial; StartListener(ta); Close; Dial;
StopTimeout(ta); StartListener(tb); Close; Dial; StopTimeout(tb); StartListener(tc)`
reachable. The round-3 shapes above have no three-slot run: the one-caller,
three-reader shape is not tractable at this carrier.

Controls. Each is run with `-model_check -nodead -bf -goal "<negation>"
-p MAX_OPERATIONS 200` and the cards shown; the negations are in each file's
header. The round-2 family (the first five) is single-caller, has a free type `T` and no
`C`, and is run with `-p DEFAULT_SETSIZE 2` and **no** `-card` (passing one raises
setup errors, though the goal is still found).

| Control | Cards | States (full, `-coverage`) | Result |
|---|---|---|---|
| `_current_buggy` | | 403014 states, 1446272 transitions, 0 uncovered | L1q, L1w, L2, L3, L4a, L4b, L5, L6 all **found** |
| `_production_buggy` | | 170605, 535816, 0 uncovered | L1q, L1w, L2, L3, L4b, L5, L6 **found**; L4a not found (170605) |
| `_gate_only_buggy` | | 281329, 1036446, 0 uncovered | L1q, L1w, L2, L4a, L5, L6 **found**; L3, L4b not found (281329) |
| `_stale_reply_buggy` | | 110012, 401516, 0 uncovered | L6 **found**; L1q to L5 not found (110012) |
| `_nowait_buggy` | | 159100, 545935, 0 uncovered | L6 **found** in 9 steps; L1q, L1w, L2, L3, L4a, L4b, L5 not found (159100) |
| `_ack_key_only_buggy` | T1 C1 | goal run | L6 **found**, 10 steps, 17054 states |
| `_pong_unkeyed_buggy` | T1 C1 | goal run | L6 **found**, 13 steps, 75894 states |
| `_query_plain_buggy` | T1 C1 | goal run | L6 **found**, 13 steps, 98172 states |
| `_repeat_buggy` | T1 C1 | goal run | L6 **found**, 14 steps, 133346 states |
| `_lose_buggy` | T1 C1 | goal run | L6 **found**, 11 steps, 35864 states |
| `_reader_restart_buggy` | T1 C1 | goal run | L6 **found**, 13 steps, 81297 states |
| `_lock_expiry_buggy` | T1 C2 | goal run | L7 **found**, 5 steps, 269 states |
| `_perlink_lock_buggy` | T1 C2 | goal run | L8 **found**, 5 steps, 359 states |
| `_write_fail_keep_buggy` | T1 C1 | goal run | L6 **found**, 15 steps, 576331 states |
| `_route_skip_buggy` | T1 C1 | goal run | L6 **found**, 13 steps, 87132 states |
| `_inline_skip_buggy` | T1 C1 | goal run | L6 **found**, 19 steps, 69630 states |
| `_registry_drop_buggy` | T1 C1 | goal run | L10 **found**, 5 steps (7 trace lines with setup), 106 states |
| `_retire_split_buggy` | T1 C1 | goal run | L11 **found**, 8 steps (10 trace lines with setup), 2022 states |

The two round-4 controls and the fixed design were run on the three-valued
connection (`hclear`, `hlive`, `hretiring`); the older controls are unchanged files
and keep the two-valued model they were written against, so their results above
are as recorded.

The first four rows are the round-2 controls, re-run unchanged on this revision
with the same results and the same shortest traces as the evaluators'. The
`_nowait` control is the round-2 design plus one operation; its trace is the
evaluator's.

Shortest traces (breadth-first). The `_current_buggy` rows admit paths the
production callers do not take (a close that does not follow a stop; a start over
an unjoined reader on an open socket), so the production control is the one that
speaks for the code as it ships. Public-API traces are labelled as such.

| Defect | Spec | Trace |
|---|---|---|
| R3-1 (L2) | `_production_buggy` | `Dial; StartListener(ta); StopTimeout(ta); Close; Dial; BrokenWrong(ta)` |
| R3-1 (L2), public API | `_current_buggy` | `Dial; StartListener(ta); Close; Dial; BrokenWrong(ta)` (a close with no stop) |
| SF3-2 (L1q) | `_production_buggy` | `Dial; StartListener(ta); StopTimeout(ta); Send; FeedCurrent(1,ta); Close; RouteShared(1,ta)` |
| SF3-2 misdelivery (L5) | `_production_buggy` | `Dial; StartListener(ta); Send; AwaitShared; StopTimeout(ta); FeedCurrent(1,ta); Close; Dial; Send; RouteShared(1,ta); AwaitShared; ConsumeAny(1)` |
| redial between send and wait (L1w) | `_production_buggy` | `Dial; Send; Close; Dial; AwaitShared` |
| two readers on a socket, production (L4b) | `_production_buggy` | `Dial; StartListener(ta); StopTimeout(ta); Close; Dial; Send; FeedCurrent(1,ta)` |
| two readers on a socket, public API (L4a) | `_current_buggy`, `_gate_only_buggy` | `Dial; StartListener(ta); StopTimeout(ta); StartListener(tb)` |
| step after stop (L3) | `_production_buggy` | `Dial; StartListener(ta); StopTimeout(ta); Send; FeedCurrent(1,ta); RouteShared(1,ta); BrokenOwn(ta)` |
| flag-only repair still fails (L2) | `_gate_only_buggy` | `Dial; StartListener(ta); CheckPermit(ta); StopTimeout(ta); Close; Dial; BrokenWrong(ta)` |
| flag-only repair still fails (L1q) | `_gate_only_buggy` | `Dial; StartListener(ta); CheckPermit(ta); Send; Feed(1,ta); StopTimeout(ta); Close; RouteShared(1,ta)` |
| late reply to an earlier request (L6), round 2 | `_stale_reply_buggy` | `Dial; StartListener(ta); Send; Await; Feed(1,ta); TimeoutPlain; CheckPermit(ta); RouteLive(1,ta); Send; Await; Consume` |
| **F7a: show() takes an un-awaited scene's ack (L6), no timeout** | `_nowait_buggy` | `Dial; SendNoWait; Send; Await; StartListener(ta); CheckPermit(ta); Feed(1,ta); RouteLive(1,ta); Consume(1)` |
| F7a, round 3, ack matched by scene id alone | `_ack_key_only_buggy` | `Dial; SendNoWait; Want(C1,ks); Send(C1); StartListener(T1); CheckPermit(T1); Feed(1,T1); RouteDeliver(C1,1,T1); Await(C1); Consume(C1)` |
| late pong answers the next ping (L6) | `_pong_unkeyed_buggy` | `Want(C1,kp); Dial; Send(C1); Await(C1); TimeoutKeep(C1); StartListener(T1); CheckPermit(T1); Want(C1,kp); Send(C1); Await(C1); Feed(1,T1); RouteDeliver(C1,1,T1); Consume(C1)` |
| late query response answers the next query (L6) | `_query_plain_buggy` | `Want(C1,kq); Dial; Send(C1); Await(C1); TimeoutKeep(C1); Want(C1,kq); StartListener(T1); Send(C1); CheckPermit(T1); Await(C1); Feed(1,T1); RouteDeliver(C1,1,T1); Consume(C1)` |
| **F7c: a repeated ack answers the next request (L6)** | `_repeat_buggy` | `Dial; StartListener(T1); SendNoWait; Feed(1,T1); CheckPermit(T1); RouteDropAck(1,1,T1); Repeat(1); Want(C1,ks); Feed(1,T1); Send(C1); Await(C1); CheckPermit(T1); RouteDeliver(C1,1,T1); Consume(C1)` |
| a lost ack skews every later ack (L6) | `_lose_buggy` | `Want(C1,ks); Dial; Send(C1); SendNoWait; Lose(1); StartListener(T1); CheckPermit(T1); Feed(2,T1); RouteDeliver(C1,2,T1); Await(C1); Consume(C1)` |
| a stop that leaves the generation open loses a reply (L6) | `_reader_restart_buggy` | `Want(C1,ks); Dial; Send(C1); StartListener(T1); Feed(1,T1); StopJoined(T1); StartListener(T1); CheckPermit(T1); SendNoWait; Feed(2,T1); RouteDeliver(C1,2,T1); Await(C1); Consume(C1)` |
| **F7b: a lock-wait expiry retires (L7)** | `_lock_expiry_buggy` | `Dial; Want(C1,kp); Send(C1); Want(C2,kp); ExpireRetire(C2)` |
| one lock per link starves the liveness ping (L8) | `_perlink_lock_buggy` | `Dial; Want(C2,ks); Send(C2); Want(C1,kp); LockExpire(C1)` |
| a failed write keeps its ledger entry (L6, three requests) | `_write_fail_keep_buggy` | `Want(C1,ks); Dial; WriteFailKeep(C1); Want(C1,ks); StartListener(T1); Send(C1); CheckPermit(T1); Feed(2,T1); SendNoWait; RouteDropAck(1,2,T1); CheckPermit(T1); Feed(3,T1); RouteDeliver(C1,3,T1); Await(C1); Consume(C1)` |
| a raising route skips the reply (L6) | `_route_skip_buggy` | `Dial; StartListener(T1); Want(C1,ks); CheckPermit(T1); Send(C1); Feed(1,T1); RouteSkip(1,T1); SendNoWait; Feed(2,T1); CheckPermit(T1); RouteDeliver(C1,2,T1); Await(C1); Consume(C1)` |
| the inline path drops an ack without popping (L6, four requests, one generation) | `_inline_skip_buggy` | `Want(C1,kp); Dial; Send(C1); SendNoWait; Await(C1); InlineSkip(2); StartListener(T1); CheckPermit(T1); TimeoutKeep(C1); Want(C1,ks); Send(C1); SendNoWait; Feed(3,T1); RouteDropAck(2,3,T1); Feed(4,T1); Await(C1); CheckPermit(T1); RouteDeliver(C1,4,T1); Consume(C1)` |

Round-4 traces (breadth-first, shortest):

| Defect | Spec | Trace |
|---|---|---|
| **R1: a predecessor's failure closes its successor (L10)** | `_registry_drop_buggy` | `Dial; Close(1); Teardown; Dial; Close(1)` (generation 1 fails and is retired; generation 2 is dialled; generation 1's caller calls `drop`, which closes generation 2) |
| **R7: a retired generation delivers (L11)** | `_retire_split_buggy` | `Dial; StartListener(T1); Want(C1,kp); Send(C1); Feed(1,T1); Close(1); CheckPermit(T1); RouteDeliver(C1,1,T1)` (the reader has read the pong; the generation is marked closed; the reader routes the pong into the sink before `shut` discards it) |

Reachability on the fixed spec (each **found**, so the invariants are not vacuous;
goals in the specification's Verification section): `afterStop(t) = 1`
(`Dial; StartListener(T1); CheckPermit(T1); StopTimeout(T1); BrokenStale(T1)`: the
one step a stopped reader may still take); an abandoned reader with a running
successor (`Dial; StartListener(T1); StopTimeout(T1); Dial; StartListener(T2)`); a
show answered by its own ack after an un-awaited scene's ack was dropped
(`Dial; StartListener(T1); Want(C1,ks); CheckPermit(T1); SendNoWait; Feed(1,T1);
RouteDropAck(1,1,T1); CheckPermit(T1); Send(C1); Feed(2,T1); RouteDeliver(C1,2,T1)`);
a stream found genuinely broken followed by a redial and a waiter; and a caller
waiting for a lock another holds. Every operation is covered in every shape
(`UNCOVERED_OPERATIONS (0)`), including `RouteDeliver`, `RouteDrop`,
`RouteDropAck`, `RepeatPong`, `LockExpire`, `TimeoutKeep` and `TimeoutRetire`.

What round 3 changed, for the record: L7, L8 and L9 are new. `Send` became `Want`,
`Send` and `SendNoWait` with typed sinks, one request lock per kind, and several
callers; the ack ledger, `RepeatPong`, `LockExpire`, `TimeoutKeep` and the
query-only `TimeoutRetire` replace round 2's single untyped sink and retire-on-any
timeout; `StopJoined` and `StopTimeout` now close the live generation and
`StartListener` is once per generation (Decision 9); the invariants are goals, not
schema conjuncts (see the finding above).

## Partitions

Each partition is a class of behaviour the model distinguishes. Tests live in
`tests/domain/` unless a path says otherwise.

### Starting and stopping (StartListener, StopJoined, StopTimeout, ExitStopped)

| # | Partition | Model operation | Existing test | Status |
|---|---|---|---|---|
| S1 | start on an open connection runs a reader | StartListener | `test_listener_thread.py::TestLifecycle` (start, idempotent start) | covered |
| S2 | start while a reader runs and is not stopping is a no-op | StartListener guard 3 | `TestAbandonedThread::test_start_while_running_and_not_stopping_changes_nothing` | covered |
| S3 | stop joins and forgets the thread | StopJoined | `TestLifecycle::test_stop_joins_the_thread_and_forgets_it` | covered (current code); the fixed design also closes the generation, see S9 |
| S4 | stop never started is not an error | none (boundary) | `TestLifecycle::test_stopping_a_listener_never_started_is_not_an_error` | covered |
| S5 | stop times out; the thread lives, told to stop | StopTimeout | `TestAbandonedThread::test_start_replaces_a_thread_stop_could_not_join` | covered (current code); see S7 and S9 |
| S6 | start abandons the unjoined thread and runs a new one | StartListener over an `lstop` reader | same test | covered (current code); the fixed design changes it, see S7 |
| S7 | start over an unjoined reader finds its generation already retired (L4a) and starts on a new dial | StartListener guards 4 and `started` | none | **GAP** |
| S8 | the abandoned reader exits at its next stopping test | ExitStopped | same test as S5/S6 (second Pong routed by the new thread) | covered |
| S9 | **a reader lives and dies with its generation**: stop, joined or abandoned, closes the generation if it is the live one (waiters fail, sink discarded); a second reader is never started on a generation that had one (Decision 9) | StopJoined, StopTimeout, `started` | none | **GAP**. Tests: (a) stop then start on an open connection redials; (b) a reply decoded but unrouted when stop is called does not skew a later request's ack; the `_reader_restart` trace as a test |

### Routing (CheckPermit, Feed, RouteDeliver, RouteDrop, RouteDropAck, RouteDead)

| # | Partition | Model operation | Existing test | Status |
|---|---|---|---|---|
| R1 | a reader routes each decoded message as it is decoded | RouteDeliver | `TestRouting::test_every_decoded_message_is_routed`, `test_a_frame_split_across_reads_is_routed_once_complete` | covered |
| R2 | a raising route costs its message, not the reader | RouteDeliver, error edge | `TestARaisingRoute` | covered |
| R3 | a reply is parked in the sink of the reader's own, live generation | RouteDeliver | `test_inbound_router.py` (ack, pong, query kept apart) tests the queue, not the generation | **GAP**: no test asserts the sink belongs to a generation |
| R4 | a reply from a retired generation is dropped, not parked (L1) | RouteDead | none | **GAP** |
| R5 | a reader whose flag is set takes at most one more routing or reporting step, the one it held permission for; with no permission it takes none (L3) | CheckPermit guard, `afterStop <= 1` | none | **GAP**. Two tests: (a) set the flag with no permission outstanding, release the reader's handler: no further route, no report; (b) set the flag after the permission was taken: exactly one step, and it lands in the reader's own generation's sink |
| R6 | the one permitted step after stop is confined: it cannot reach the replacement (L1, L2) | RouteDead or BrokenStale after StopTimeout | none | **GAP**. Test: stop (times out), redial, then let the permitted step run; the replacement's sink and socket are untouched. This is the test that stands in for "the flag is hygiene, not safety" |
| R7 | a waiter on the new generation is never answered by an old generation's reply (L5, SF3-2 symptom) | RouteDeliver after RouteDead | none | **GAP** |
| R8 | blocked route on message k of a chunk, stop times out, successor started, route released: message k+1 is not routed | RouteDead, buffered | none (the review's proposed test) | **GAP** |

### Matching a reply to its request (M1 to M4)

| # | Partition | Model operation | Existing test | Status |
|---|---|---|---|---|
| M1 | a pong is delivered only to the ping whose `ts` it echoes; a pong with another `ts`, a repeated pong, a pong with no ping in flight, are dropped on arrival | RouteDeliver (kp), RouteDrop, RepeatPong; `pong_unkeyed` | none | **GAP**. The Hub must make each ping's `ts` strictly increasing within a generation (the wall clock alone can repeat); a test sends two pings within one clock tick |
| M2 | an ack is matched by its position among the acks owed on the generation, un-awaited scenes included: the ack of a `send_scene` is routed and dropped, and the `show()` after it gets its own (Decision 5d) | RouteDeliver (ks), RouteDropAck, the `led` ledger; `_nowait`, `_ack_key_only` | none | **GAP**: see F7a, which is this partition's test |
| M3 | a query response is delivered to the query in flight; a response with no query in flight is dropped on arrival; a query that times out retires its generation (Decision 5e) | RouteDeliver (kq), RouteDrop, TimeoutRetire; `_query_plain` | none | **GAP**: see F7 |
| M4 | **mandatory**: the `scene_id` of an ack is a cross-check, never a key: an ack whose id differs from the oldest outstanding entry's retires the generation. Limit: the replicator pushes one scene id many times, and a shift among acks of one id is invisible to the check (it persists until an ack of another id arrives), so the check is defence in depth and the guarantee is assumption A1 with the display-side rule (F7c) | none (the model gives every scene one id, the worst case) | none | **GAP**. Test: write scenes `a`, `b`; make the display ack `b` first (or drop `a`'s ack); the generation retires. Test the limit too: two scenes of one id with the first ack dropped is *not* detected, which is why F7c's backpressure test must hold |

### The Hub's failure paths (W1 to W3)

| # | Partition | Model operation | Existing test | Status |
|---|---|---|---|---|
| W1 | a write that raises after its ledger entry was appended retires its generation (or the entry is appended only after the write returns, under `_lock`); the next `show()` is answered by its own ack | Close; `_write_fail_keep` | none | **GAP**. Test: make `sendall` raise once after the append; the generation is retired, the next request redials and gets its own reply |
| W2 | a reply whose routing raises is not skipped: routing a pong, ack or query response is infallible, or a failure retires the generation; business events keep log-and-continue (`ListenerThread._routed_one`) | BrokenOwn; `_route_skip` | `TestARaisingRoute` asserts log-and-continue for every message and must be narrowed to business events | **GAP**, and an existing test to narrow |
| W3 | the inline read path (no listener) pops the ledger for every ack it reads, interleaved ones included, applies M1 to M3, and reads under the generation's socket lock, never concurrently with another kind's `sendall` (an `SSLSocket`, DES-090, does not allow it; `DisplayConnection.receive` takes no lock today, `poll_chunk` does) | the specification of RouteDeliver/RouteDrop/RouteDropAck for both paths; `_inline_skip`; the lock half is outside this model (companion `docs/listener_locks.tex` to come) | none | **GAP**. Test: with no listener, a ping waits while an un-awaited scene's ack arrives; then a `show()` gets its own ack. Lock half: two kinds in flight on a TLS pair, no concurrent read and write |

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

### Closing, redialing and the request (Dial, Close, Want, Send, SendNoWait, Await, AwaitFail, Consume, TimeoutKeep, TimeoutRetire, LockExpire)

| # | Partition | Model operation | Existing test | Status |
|---|---|---|---|---|
| C1 | open dials; open on an open connection is a no-op | Dial guard | `test_display_connection.py` (open tests) | covered |
| C2 | a failed dial leaves the connection closed | Dial, error edge | `test_display_connection.py::test_a_dial_that_fails_leaves_the_connection_closed` | covered |
| C3 | closing a closed connection is not an error | Close, idempotent | `test_display_connection.py::test_closing_a_closed_connection_is_not_an_error` | covered |
| C4 | closing discards queued replies and fails waiters | Close | `test_inbound_router.py::test_reset_discards_replies_a_dying_listener_left`, `test_a_listener_that_exited_fails_the_waiter_instead_of_timing_out` | covered |
| C5 | a redial carries no reply, no ledger entry and no waiter of the generation before | Dial | none that asserts it across a close and redial | **GAP** |
| F7 | **a query that times out retires its generation** (`close_if_current(g)` with that request's generation); the next query, on the redialed generation, is never handed the earlier query's late response (L6) | TimeoutRetire; `_query_plain` | none | **GAP**. Test: send a query to a display that answers after the budget; the caller times out and the connection closes; the late response, if it arrives at all, is dropped; the next query is answered only by its own response. A *ping* or a *scene* that times out does **not** retire (TimeoutKeep, M1, M2) |
| **F7a** | **a `send_scene` followed by `show()` on one generation: `show()` gets its own scene's ack, and the ack sink stays bounded across N replicated scenes** (L6, L9) | SendNoWait; RouteDropAck; `_nowait`; the reachability trace | none | **GAP**, and it **fails against the code today**: every replicated scene leaves one `AckMessage` in `ReplyQueues._ack`, nothing consumes it, and luxd's link lives for days. Test: replicate N scenes, then `show()`; assert the ack is the show's (the display acks in order; make the display slow to ack the first) and that the ack queue's length is 0 after N scenes. Include two scenes with **one scene id**: the ack count, not the id, decides |
| **F7b** | **a budget that expires while waiting for the request lock fails the caller without retiring the generation or touching any other caller; a liveness ping is not delayed behind a slow query** (L7, L8) | LockExpire; `_lock_expiry`, `_perlink_lock` | none | **GAP**. Tests: (a) hold a ping in flight, start a second ping with a budget shorter than the first's remaining wait: it fails, the generation is still live and the first ping completes; (b) hold a query in flight (display slow), run a liveness ping: it is not blocked and returns its own pong |
| **F7c** | **display side: the display never drops a reply on a live connection, answers each request at most once, and acks each scene exactly once, in order** (assumptions A1 and A2 of the specification; they underlie the ack ledger and the query rule) | the `repeat` and `lose` controls; `Sever` in the fixed model | none | **GAP**, in `tests/` of the display (`test_render_loop*` or the socket-listener tests): one ack per `SceneMessage` the Hub's link sends (a scene the display rejects for identity, `reject_scene_unless_hub`, is today not acked at all: a Hub link is never rejected, but the test must say so), one pong per ping, one `QueryResponse` per `QueryRequest`, none duplicated by a reconnect or a retry; replies of one connection in the order of its requests. **Backpressure test**: the display as shipped *fails* it (`_handle_scene` discards the result of `send_to_client`, which returns `False` at the frame deadline and nothing resends; `socket_server.py`, `bounded_send.py`). Fill the Hub side of the socket (a Hub that does not read), send N scenes: assert that N acks arrive in order, or that the display closed the connection. The rule (leader's ruling): when `send_to_client` defers or misses its deadline the display closes that connection, and the Hub redials through `ClientRegistry`. The same holds for pongs and query responses (harmless under the design, but never silently dropped) |
| T1 | a request sent on generation g is answered only from g; a redial between send and wait fails the waiter, never consuming g+1's reply (Decision 4, L1w, L5) | Send; AwaitFail | none | **GAP**. `send` must return the generation; test by redialing in a seam between the send and the wait |
| T2 | a waiter on g fails promptly when g is closed or g's reader exits, even while an abandoned reader of g-1 is alive (Decision 6) | Close, StopJoined, StopTimeout, BrokenOwn, TimeoutRetire fail the waiter; promptness is a liveness property the model does not check | none (`test_a_pending_reply_fails_when_the_listener_exits` covers the link-level listener only) | **GAP** |
| T6 | **the inline read path** (`DisplayReplies.typed` and `ack` when no listener runs) reads the request's own generation's socket, applies the same matching and the same ledger pops (M1 to M3, W3), and never reads the replacement after a redial in the gap (D4 inline path) | the inline form of Await and Consume | none | **GAP**. Test: with no listener, redial between send and wait; the wait fails instead of reading the new socket |

### Socket and thread realization

| # | Partition | Model operation | Existing test | Status |
|---|---|---|---|---|
| T3 | an abandoned reader never reads the replacement's socket (L4b, the production route to two readers) | Feed guard `lgen = curGen` | none | **GAP**: stall a reader past the join after it passed `is_open`, redial, release it; assert it read nothing from the new socket, and that `poll_chunk` is not reaching `require()` |
| T4 | `shutdown(SHUT_RDWR)` before `close()` releases a sender wedged in `sendall` and a reader blocked on `_lock` behind it (Decision 3); also on an `SSLSocket` (DES-090): the raw socket's `shutdown`, not `unwrap()`, which blocks on a wedged peer | the realization of StopTimeout closing the generation | none | **GAP**; pairs with row D |
| T5 | the business-event policy: closing a generation does not drain the link-level event queue; events queued before a close and events a straggler routes after it are both delivered; interaction handlers may run on two threads, out of order (Decision 7) | none (outside L1 by design) | `test_inbound_router.py::test_reset_discards_events_queued_before_it` asserts the opposite and must change with the fix | **GAP**, and an existing test to rewrite |

### The registry and the two steps of a retirement (X1 to X8, round 4)

Both rows come from the final review (silent-failure finding 2, invariant
review F5): the defect class the generation closed at the link, *a stale party
closes or feeds its successor*, found again one layer up. Rulings R1 and R7.

| # | Partition | Model operation | Existing test | Status |
|---|---|---|---|---|
| X1 | **`drop(g)` with `g` the current, live generation closes it** (a probe that found a live display silent) | Close, `g? = curGen` | `tests/domain/test_link_generations.py::TestDropNamesTheDialThatFailed::test_a_drop_for_the_current_dial_closes_it`; the callers' side in `tests/operations/test_display_connection.py::test_query_maps_a_send_failure_to_timeout_and_drops` and `tests/domain/test_recovery.py::test_recovery_drops_the_dial_the_failed_send_went_out_on` | covered |
| X2 | **`drop(g)` with `g` retired and a successor `g+1` live closes nothing**: the successor stays open, its waiters wait, its manifest is not resent (L10) | DropStale; `_registry_drop` | `tests/domain/test_link_generations.py::TestDropNamesTheDialThatFailed::test_a_drop_for_a_replaced_dial_leaves_the_new_dial_open`; at the connection, `tests/domain/test_display_connection.py::TestCloseIfCurrent::test_a_replaced_generation_s_report_changes_nothing` and `tests/domain/test_listener_thread.py::TestAStaleReportCannotTouchTheReplacement::test_a_report_for_a_replaced_dial_leaves_the_replacement_and_its_waiter`. Each dropping caller passes the dial it holds: `tests/operations/test_display_connection.py` (query and ping adapters), `tests/test_liveness.py`, `tests/domain/test_recovery.py` | covered |
| X3 | `drop(g)` with `g` retired and no successor is a no-op (the generation retired itself) | DropStale, `held /= hlive` | `tests/domain/test_display_connection.py::TestCloseIfCurrent::test_closing_twice_is_a_no_op_the_second_time` (the connection level: a retired dial, no successor, `close_if_current` returns false and changes nothing). There is no registry-level test of the same case | covered at the connection; the registry's `drop` delegates to it |
| X4 | there is no `drop()` without a generation: a caller that holds none (the registry's redial after a failed manifest) takes the current one under the registry lock, once | the type of Close | `tests/test_client_registry.py::TestDropHasNoFormWithoutADial` (the dial is a required parameter; a drop naming nothing is refused) | covered |
| X5 | **a reply is not parked once the generation is marked closed**, even when the reader had read the chunk before the mark and the sink is not yet discarded (L11) | RouteDead in the window; `_retire_split` | `tests/domain/test_link_generations.py::TestARetiredDialNeverDelivers` (`test_the_rest_of_a_chunk_is_not_routed_once_its_dial_is_retired`, and the inline-read form `test_the_rest_of_a_chunk_read_inline_is_not_routed_once_its_dial_is_retired`: the dial is retired mid-chunk and the later message is not routed); at the sink, `tests/domain/test_reply_sink.py::TestARetiredDialNeverDelivers::test_a_reply_delivered_after_the_discard_answers_nobody_and_raises_nothing`. The sub-step order inside the window (between `mark_closed` and the discard) is held by X7, not by a seam test of its own | covered |
| X6 | the reader leaves its loop when its generation is closed, not only when its stopping flag is set: the rest of an already-read chunk is dropped (it is already so for `_routed`'s loop test in the worktree; the sink check is what makes it hold across the window) | RouteDead | `tests/domain/test_listener_thread.py::TestTheReaderLoopStopsOnItsDialsRetirement`; the business-event half (a business event in the rest of the chunk is not queued) in `tests/domain/test_link_generations.py::TestARetiredDialNeverDelivers::test_the_rest_of_a_chunk_is_not_routed_once_its_dial_is_retired` | covered |
| X7 | the closed flag `deliver` reads is written under the **sink** lock in the same hold as the mark, and read under the sink lock in the same hold as the put (the realisation of the guard of RouteDeliver) | the guard `held = hlive` of RouteDeliver, atomic with the put | at the dial, `tests/domain/test_link_generations.py::TestTheClosedMarkIsOneHoldWithTheSinkDiscard` (a dial does not read as closed while a delivery holds the sink, and a reply delivered once it reads closed is parked for nobody); at the sink, `tests/domain/test_reply_sink.py::TestTheClosedFlagIsOneHoldWithTheDiscard` (a delivery queued behind the discard sees the flag; the flag is written and read under the sink's lock). No stress test and no AST guard was written; the deterministic lock-hold tests stand in for both | covered |
| X8 | a reply parked before the mark is still delivered to its own waiter, who may consume it in the window; a waiter whose reply was not parked fails at teardown | Consume in `hretiring`; Teardown | `tests/domain/test_reply_sink.py::TestARetiredDialNeverDelivers::test_a_reply_that_arrived_before_the_discard_is_still_taken` (a parked reply survives the discard and `await_reply` returns it); the teardown half in `tests/domain/test_reply_sink.py::TestWaiting::test_discarding_the_sink_fails_the_waiter_at_once` | covered |

### Invariants and deadlock

| # | Property | Existing test | Status |
|---|---|---|---|
| L1 | replies and the waiter stay within the live generation | none | **GAP** (R3, R4, R7, R8, T1) |
| L2 | a generation is closed only by the link, a stop, a query's timeout, or its own reader | none | **GAP** (B5, B6, S9) |
| L3 | a stopped reader takes at most one step | none | **GAP** (R5, R6) |
| L4a | one reader per live generation | none | **GAP** (S7, S9) |
| L4b | a reader holds only its own generation's bytes | none | **GAP** (T3) |
| L5, L6 | no wrong reply is consumed | none | **GAP** (R7, T1, M1 to M3, W1 to W3, F7, F7a) |
| L7, L8 | lock waits | none | **GAP** (F7b) |
| L10 | no successor is closed by a predecessor's failure | X1 to X4 | covered |
| L11 | a retired generation parks no reply for a waiter | X5 to X8 | covered |
| L9 | the sink is bounded | none | **GAP** (F7a) |
| D | the lock graph: one request lock per kind, then the state lock, then a queue lock, with `_lock` a leaf; a report never takes a request lock and never `_lock`; a caller waiting for a request lock holds nothing | `test_single_writer.py` covers the single-writer discipline for the replicator, not these locks | **GAP**: assert the state lock is not `_lock`, that a report from another thread still closes the generation while a sender is blocked in `sendall` on a wedged peer, and that two request kinds never serialise (F7b) |

## What the implementation mission must add

The gaps S7, S9, R3 to R8, M1 to M4, W1 to W3, B5 to B8, C5, F7, F7a, F7b, F7c, T1 to T6 and D
are the regression tests of the design, and each fails against today's code. B5 is
the test named in the R3-1 review. R8 is the SF3-2 review's test. Neither is
sufficient alone: the stopping-flag control passes both and still violates L1 and
L2 across the window between the test and the act. The tests that distinguish the
design from that repair are R4, R6, R7 and B7: they hold the reader between its
look and its step, then replace the connection. The tests that distinguish the
round-3 design from the round-2 one are F7a (an unawaited send), F7b (a second
caller) and F7c (a display that answers twice).

One existing test asserts behaviour the design reverses (T5,
`test_reset_discards_events_queued_before_it`); it is rewritten with the fix, not
deleted. F7 and S9 are behaviour changes for callers, not only internal ones: a
query that times out now costs the connection, and a library caller that stops its
listener and starts another on one connection must redial. The assumptions A1 and A2
of the specification are statements about the display; F7c pins them. If the
display may be another implementation (DES-090), they cannot be pinned, and the
alternative is a request id on the wire (the specification's Options paragraph).

The implementation rules, numbered, are in the mission result
(`.tmp/missions/results-listener-model-r3/m-2026-10-23-024.md`).

Re-run `fuzz` and the model-check, and revisit this table, whenever the reader,
the connection, the reply queues, the replicator's send path or the liveness probe
change how a reader is started, stopped or allowed to act, how a request is sent
and awaited, or which caller may send while another waits.
