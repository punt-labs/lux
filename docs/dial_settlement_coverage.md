# Dial settlement: coverage audit

Companion to [dial_settlement.tex](./dial_settlement.tex) and its controls. It lists the
partitions of the model and the tests that cover them. The implementation follows the
model. Each row names the test that was red on the code as it stood at `41e90082` and is
green on the design. The design column says what the test does; the mapping that follows
names it. A row marked GAP has no test.

Governs: `src/punt_lux/domain/hub/{display_connection,dial_reader,display_listener,
listener_thread,display_replies,reply_sink,dial_generation,reader_slot,dial_drain,settler,
bounded_ask,dial_end,dial_socket}.py`, and since round 5 `src/punt_lux/{bounded_send,send_timeout}.py`.
Re-run `fuzz`, the model-check and every control whenever the end, settle or slot paths
change.

## The properties

| Id | Claim | Status |
|----|-------|--------|
| S0 | (round 5) No settle decides from nothing: a holder never reaches its decision with no cause recorded, no end of file observed and no Hub request (the code's `decide` raises `ValueError`, and a listener dies holding the slot) | checked: `s0bad` not found over 2483517 states (round 6); `SDecideNone` uncovered by the deadlock check; `stop_no_request` trips it, `SPStart, StOk, RReadErr, SDrain, SDecideNone` (2847 states, depth 5) |
| S1a | An ended or end-requested current dial is settled by a party already running, with no timer. Holds only if the three atomicity obligations hold; broken, the dial degrades to the 2 s bound and an undrained capture | checked: goal not found (round 3: 90905 states; round 4 with the writer and `WStall`: 2068661 states; round 5: 2267293 states; round 6, with a writer that may stall or keep progressing: 2483517 states); every round-9 control trips it |
| S1b | The same behind a holder that never makes progress, by the bound | checked: goal not found (round 6, 2483517 states; a stuck writer is stuck, whether it stalls or keeps progressing; a settler behind a held lock has `SDrain` or the timed `SDrainLate` and counts as in flight, as a waiting asker does; so does a keepalive at `pping`). Liveness the state goals cannot see is shown by the **no-rescuer** deadlock check: scratch copies with `SPStart` and `IAcq` given the unsatisfiable guard `pc a = pidle and pc a = pdone`. The design has no deadlock (78581 states), nor with the write deadline broken (`WDeadline` disabled, 78581), nor with the keepalive waiting for the lock (78581). `unbounded_write` (both together, the code before round 5) deadlocks: `WLock, WStall, DStartUnresp, Expire, Die, Block` (1371 states, depth 6). `drain_no_late` with the deadline broken deadlocks: `WLock, Expire, WStall, DStartDisp, Die, Block, RecEnd, SUGrant(aDi)` (3869 states, depth 8). A writer that keeps progressing for ever is a livelock no deadlock check sees; jra checked it with ProB's LTL checker (m-2026-10-26-022, evaluation of round 1): `G({current = fset & (ended /= nocause or hubreq = fset)} => F {current = fclear})` under weak fairness on every operation (`WEF`). The check disables `Die` and `IAcq`, because `WEF` alone makes `Die` fair, the display eventually dies, `WProg` stops and the deadline takes over, so a perpetually progressing writer never survives and the check is vacuous. Results: the design TRUE (65 s, 0.97 GB); `drain_no_late` FALSE, a lasso of 16, `Ack, Block, DStartDisp, SPStart, WLock, HubReq, SUGrant(aSp), Expire, WStall` then `(WProg, WProg, Expire)` for ever, the stopper waiting behind a perpetually progressing writer with the socket readable and no late path; the design without fairness FALSE (the formula is not trivially true). Weak fairness suffices because a settler at `pset` always has `SDrain` (unreadable) or `SDrainLate` (lock held, readable) enabled, neither is disabled by `WProg` or `Expire`, and readability persists until a drain. Scratch files `.tmp/jra-r1/r12-live-*.tex`, output `.tmp/jra-r1/r12-ltl-*.txt`, not committed. The late capture behind a progressing writer is reachable (20167 states). `defer_only` deadlocks, `timer_hub_only` trips the goal |
| S2 | A dead display's end is captured only after a drain that began after it was recorded | checked: `s2bad` not found; `split_settle` and `stop_skip_drain` trip it |
| S3 | One capture per dial | **structural** (every capture guarded by `current`); `s3_unguarded` trips it |
| S4 | The captured cause is the first recorded | **structural** (one first-wins writer); `s4_overwrite` trips it |
| S5 | No recorded cause contradicts the observation: a display dead when observed is never recorded as hub; (round 4) a writer never records a display end for a display that is alive; and (round 5) a writer never records a cause while a Hub request is pending, because the request refuses writes and its end is the Hub's, charging nothing | **structural** (the cause is a function of the observation, and `WRec` records only when no request is pending); `hub_record`, `hub_peek`, `writer_records_display` and `writer_split_record` trip it. `writer_split_record` is one point, the check and the record under two lock holds: `WLock, SPStart, Die, WSendDead, WCheck, HubReq, WRec` (8653 states, depth 7). The writer clause is **structural** in the design: the design's `WRec` flag names only the live-display clause, and only the control's record, over a stale check, names the writer clause, where it is live. Rule 7b is therefore no longer policy. (Round 6) The bound's clause, too: past the bound a refused asker records `hub` when nothing is recorded, never its own cause over a pending request (`Timeout`); `bound_records_asker` (the code's `BoundedAsk.settle_by_bound` calling `generation.end(cause)`) trips it, `SPStart, WLock, HubReq, Die, WSendDead, WRec, SURefuse, Timeout` (24869 states, depth 8), structurally false in the design |
| S7 | (round 6) No `unresponsive` verdict while progress occurred within `D`, so a slow but live write is never cut short. The model covers the **writer's** verdict only (`WSendTimeout`, `WDeadline`); the keepalive's clause is an obligation on the code: the keepalive reads the socket's one last-progress time, counting bytes in either direction, and gives no verdict within `D` of it (P31) | writer's verdict checked: `s7bad` not found over 2483517 states; **structural** in the design (both steps require `prog = fclear`, and `prog` is faithful from `WLock` to the verdict); `whole_write_deadline` (round 5's whole-write deadline) trips it, `WLock, WProg, WSendTimeout` (244 states, depth 3). Keepalive's verdict **not checked**: the model clears `prog` when the writer leaves the lock and counts no incoming byte, so `KPing` may fire at once after `WSendDone` or an `Ack`, and no step flags it. That makes the model's keepalive more ready to give up than the code's: a superset for S0 to S6, and for S7 exactly the violation the model cannot see |
| S6 | A scene on the wire of a current dial is in the ledger once its writer lets go of the socket lock (an end never withdraws the entry; a capture before the entry is the `a1late` exception) | checked: `wire = fset & ledger = fclear & lk = fclear & current = fset` unreachable over 2483517 states (round 6); `writer_owe_refused` (1866 states, depth 5) and `writer_records_display` each reach it |
| S2w | A drain that finds the socket readable never reports "nothing more" | **structural** (the content is `SDrain`'s guard; `gu` is identically clear in the design); `drain_gives_up` sets `gu` and trips `s2bad` (10117 states, depth 7). The timed-out branch that replaces the give-up, `SDrainLate`, is checked: the deadlock check passes (56 of 57 operations covered, the 57th the unreachable `SDecideNone`), S1a and S1b hold, and it ends in the bound's capture flagged `s2lat` |

S2's carve-outs, each with its own flag and bound: decode-error ends capture undrained
(`s2dec`; the acks behind the bad frame, once); the bound captures undrained, for a display
end and for an unresponsive end alike (`s2blk`; every ack queued while the holder stalled,
including the holder's undelivered buffer, after 2 s; an accepted over-charge, DES-102); and,
for the holder's settle only, a live display (unresponsive end) may ack after any drain (one
drain-to-capture gap). The residual of S5 widens to the bound when the bound fires
(`s5blk`). The classification of a send timeout as the display's end is a separate bound
(B3); the send-timeout obligation is rmh's and is not modelled.

### Refinement of the abstract model

The abstract model is `crash_attribution_inflight_ack_drain.tex`, not `crash_attribution.tex`
alone. The gluing is an inclusion, not an equality of state: concrete charges are a subset of
abstract charges (the unresponsive re-drain reads acks the abstract model says were never
sent). The inclusion gives A2. A1 holds for a different reason: the only acks the concrete
settle reads beyond the abstract ones are, by T11, of scenes that survived a frame, so the
poison scene is never among them. Six paths have no abstract counterpart and are
deliberate exceptions to A1 or A2, each with its bound:

| Exception | Flag | Fails | Bound |
|-----------|------|-------|-------|
| a display charge with an ack unread, from a broken stream | `s2dec` | A2 | the acks behind the bad frame, once |
| the bound's capture of a display end | `s2blk` | A2 | every ack queued while the holder stalled, after 2 s |
| the bound's capture of an unresponsive end | `s2blk` | A2 | as above; flagged since round 3 |
| `hub` recorded by the bound for a display already dead | `s5blk` | A1 | a poison death is carried and not charged; a later ack read clears it; after 2 s, once |
| a display or unresponsive end captured undrained by the settler's own late capture, a writer having held the socket lock past the ceiling with an ack or end of file readable | `s2lat` | A2 | the acks readable at that moment; ceiling (3.5 s) plus bound (2 s), 5.5 s; since round 6 reached behind a writer that keeps progressing past the ceiling (a slow live link) or one that breaks its deadline; accepted over-charge, like `s2blk` |
| a scene written while a capture lands between `sendall` returning and `owe_ack` (`WOweLate`): in neither the captured ledger nor, for a `hub` capture, the carry. An **under**-charge | `a1late` | A1 | one scene per dial, and only for a capture in that window (any capture: a Hub request, a decision on an unreadable socket, the bound, a decode error). The write raises `ConnectionClosedError`, an `OSError`; `SendRecovery.recover` re-marks the batch's scenes (`_repaint`) for every failure but a shutdown flush, so the scene goes out on the next dial and a death it causes is charged there: late by one dial, not lost. Two qualifications: (a) it is charged on the next dial only if it kills that display too (a deterministic poison does; a scene the agent cleared meanwhile is not re-sent and needs no charge); (b) the first death, which does not name it, charges only the other scenes in that dial's ledger and carry |

## The design the model proves

One rule: settlement belongs to the holder of the reader slot; everyone else asks.

1. **The door is the slot.** `close_if_current` leaves `DisplayConnection`'s interface.
   `ReaderSlot` hands its holder a `Settler` (listener: born-holding or `claim_for_listener`;
   inline: `inline()`; a releaser taking over: `release`). `Settler.settle()` is the only
   code that captures, except the bound's own capture. No `by_reader` flag. The model's
   `SettleGone` for the listener is unreachable until the bound fires.
2. **Ends record or request.** Display and unresponsive ends record the cause, first wins.
   A Hub end sets `hubreq` and records nothing; it refuses writes and fails waiters at once.
3. **A refusal leaves a debt, atomically.** Free slot: take it. Held: set the debt, in the
   same critical section as the observation.
4. **A release honours the debt, atomically.** Read the debt and free the slot in one critical
   section; with a debt, keep the slot, settle, look again. Every path that gives up the
   reader role releases this way; `start_on` on an ended dial releases before it raises.
5. **Settle is two steps.** Drain to the point of blocking, noting end of file; then fix the
   cause by the dial's first-wins `end(...)` (end of file is `display`, else `hubreq` is
   `hub`, else the recorded cause stands). A record made after the drain began owes a fresh
   drain. Both settlers, the listener and the releaser, run these steps.
6. **The wait is bounded (T15).** A refused asker waits; after the bound (the stop join, 2 s)
   it records its cause with the first-wins record and captures. A hub capture charges
   nothing and carries its scenes. The bound applies to **every** asker: armed by a Hub
   request alone, a display end behind a stalled holder is wedged (`timer_hub_only`).

7. **The writer (round 4).** (a) Once the bytes are on the wire the owed ack is recorded
   whatever the end state: a Hub request or a recorded cause does not refuse it; only a dial
   already captured does. (b) A write that fails after a Hub request is the Hub's failure: the
   writer records no cause (it tests `closing`, not the recorded `ended`) and the settler's drain
   finds a display that really died. Round 5 makes the check and the record one step under the
   sink's lock (`ReplySink.end_by_writer`), and gives it a checked property: S5's writer clause,
   a writer never records a cause while a Hub request is pending, which `writer_split_record`
   (the two lock holds the code had) trips. (c) A drain that
   finds the socket readable and the lock held by a writer *waits* for it, up to the ceiling
   (`SEND_TIMEOUT_CEILING_SECONDS`, 3 s, set strictly above the 2.5 s the platform probe admits
   for the send timeout; the measured timeout is 1 s on Linux and 2 s on macOS). A socket that is
   not readable is looked at without the lock. A writer that fails or times out releases the lock
   within the ceiling, so its acks are read. A writer that makes slow partial progress (`WStall`) does not, and rule 6
   does **not** bound that case: it is armed by a refused asker, and a settler that took the slot
   itself has none. At the ceiling the drain reports itself incomplete (`DrainIncompleteError`),
   and the settler hands its capture to the bound (`ReaderSlot._late`): it waits the bound (2 s)
   for anyone else to settle, then records its cause and captures undrained (`SDrainLate`,
   `LateCapture`). The settle ends within ceiling plus bound, 5 s, with no asker; the capture
   shuts the socket, which wakes the stuck writer (`WStuckOut`). Two obligations on the code, which
   a model with one writer cannot see: every capture shuts the socket, so a TLS `sendall` wedged on
   a display that reads nothing returns within that bound; and the ceiling is paid at most once
   per settle, because after the end is recorded or requested no new writer passes
   `_require_open`, so the drain waits for at most the one writer in flight. The premise misses one
   case: a settle that starts on an observed end of file with nothing yet recorded, where a new
   writer can still pass `_require_open` during the first drain. On the same-host Unix socket that
   writer fails at once with EPIPE and records the display's end, which closes the door, so the
   bound stays 5 s; across hosts (TLS) it can wait out its own send timeout first, and the worst
   case is 3 + 3 + 2 = 8 s. With rule 7d (round 6) that writer is bounded by `D` of no progress:
   a settle whose writers stall waits at most `D` per drain, `2D` with the re-drain. A drain
   that reaches the ceiling hands the capture to the late path at once and is not followed by a
   re-drain, so behind a writer that keeps progressing the settle ends within ceiling + 2 s; the
   worst case is a first drain behind a writer that stalls and a re-drain behind a second that
   keeps progressing, `D` + ceiling + 2 s = 8 s. The late capture is
   the fifth exception to A2 (`s2lat`). The lock order
   `rq < sl < st < lk < qu` is kept: the waiting settler holds no lock the writer takes, and the
   writer, which takes `qu` for the ack under `lk`, waits on nothing the settler holds. The
   model is the code as built on `fix/lux-ghhf-r3-fixes`; the round-1 idea of a polling re-drain
   is not what was built.
   (d) **A no-progress deadline `D` (round 6, the leader's ruling on C3/S2).** A dial is
   unresponsive when no byte has moved on it for `D` while some party needs it to move: a
   writer that is sending, or a ping, a query or a writer waiting for the socket lock. Round 5's
   whole-write deadline cut short healthy slow cross-host writes: the scene never reached the
   ledger, the live display was reaped, and the resend looped (control `whole_write_deadline`,
   property S7). The model abstracts time by `prog` ("less than `D` since the last byte moved,
   or since a writer began"): `WLock` and `WProg` set it, the environment's `Expire` clears it,
   and the writer's deadline (`WSendTimeout`, `WDeadline`) and the keepalive's verdict
   (`KPing`) are enabled only with `prog = fclear`. A writer leaving the lock also clears `prog`,
   and an incoming byte is not counted; both make the model's keepalive more ready to give up
   than the code's, a superset for S0 to S6, but for S7 the wrong direction, so S7 is checked for
   the writer's verdict only. A writer that keeps progressing is never cut short; the keepalive
   treats progress within `D`, a byte in either direction, as liveness and needs no lock to see
   it, an obligation the model does not check (P31).
   A settle behind a progressing writer falls to the late path (`SDrainLate`, `LateCapture`),
   whose capture shuts the socket and so ends the writer (`WStuckOut`); for such a writer the
   late path is no longer only a defence. **Bounds:** a stalled dial ends within `D` of its last
   progress (the writer's deadline, or the keepalive's verdict); a settle behind a writer that
   stalls waits at most `D` and reads every ack, since the ceiling stays strictly above `D`; a
   settle behind a writer that keeps progressing ends within the ceiling plus the 2 s bound.
   **Obligations on the code** (the model cannot see time): the socket tracks the time of its
   last progress, one time for the whole socket; every write under the lock (`send_scene`,
   `send_ping`, `send_query`, `send`) and every wait for the lock is bounded by `D` of no
   progress measured on that time, never by `D` of elapsed time; the keepalive's verdict reads
   the same time, counting bytes in either direction (a completed write and an incoming ack
   both count), so it gives no verdict within `D` of any byte and needs no lock to give one;
   S7's keepalive clause rests on this obligation alone;
   `KPing` and `WDeadline` are each one step, sound only under these obligations. On TLS the
   bound is the user-space bounded send, since `SO_SNDTIMEO` bounds nothing. Constants: `D` =
   2.5 s and the ceiling 3.5 s, as ruled; the model needs only ceiling > `D`, and nothing in it
   asks for a change.

8. **A reader that leaves on the stop flag asks for the Hub's end (round 5).** `stop()` sets
   the flag, then asks; two steps. A reader that leaves on the flag, at the top of its loop
   (`RStop`) or through a read that failed in that window (`RReadErr`), calls `request_hub()`
   before it settles. Every settle then starts from a recorded cause, a request, or an end of
   file the drain will see, and no writer passes `_require_open` in the window. The drain itself
   no longer waits for a cause (round 4's guard hid the defect); a settle with nothing to decide
   from is `SDecideNone`, the code's `ValueError`, and S0 says it never happens.

The code as it stands cannot meet S1 to S5 without rules 1, 2 and 6. Patching the three
round-9 traces (release in `start_on`, re-check after the inline release, record before the
read) leaves S5 open, leaves `by_reader` a default, and leaves the Hub end's escape from a
stalled holder missing.

## Partitions

| Partition | Model operations | Test design (two threads where stated) |
|-----------|------------------|-------------------------------|
| P1 start fails on an ended dial | `StFail`, `StRel0`, `HubReq`, `SURefuse`/`SUGrant` | Hold `open_as_hub` between `open_listening` and `start_on`; end G2 on thread B (`_write_failed`); release A. Assert G2 not current, one `DialDeath(display)` with G2's owed scenes, the next `asks()` redials. Red on HEAD. Control: `start_fail_buggy` |
| P2 start fails on a healthy dial (thread cannot start) | `StFail` with `current` | Make `Thread.start` raise; assert the slot is free, then the Hub end settles synchronously and the dial is not current |
| P3 stop exits on its flag, display end lands in the window | `RNotice`, `SDrain`, `SDecide`, `SPStart`, `HubReq`, `RecEnd` | Wrap `DialDrain.run` so that when entered on a dial with no cause, `end("display")` lands first; send `a`, queue `Ack(a)`, `link.close()`; assert no death names `a`. Two reads is red. Control: `stop_skip_drain_buggy` |
| P4 inline holder past its last check | `IAcq`, `ILastSkip`, `RecEnd`, `SURefuse`, `RelOwes`/`RelFree` | Hold A between `_settle_if_ended` and the slot release (wrap the `inline()` exit); fail a write on B; release A. Assert `not link.is_connected` and the death is queued, with the bound disabled so the timer cannot rescue it. Red on HEAD. Control: `inline_strand_buggy` |
| P5 refusal and debt are one critical section | `SURefuse`, `SUSetDebt` | Instrument the slot's lock; interleave a release between the observation and the debt. Control: `atomic_refuse` (S1a) |
| P6 release and debt-read are one critical section | `RelFree`, `RelRead` | Interleave a refusal between the release's debt-read and the free. Control: `atomic_release` (S1a) |
| P7 the post-drain record is first-wins, with a re-drain | `SDrain`, `SDecide`, `SRedrain` | A writer records `display` between the settler's drain and its capture, with an ack queued after the drain; assert the second drain delivers it and no death names it. Both settlers: the no-reader settle and the listener. Control: `split_settle` (S2) |
| P8 display dies before the Hub end is decided | `Die`, `SPStart`, `HubReq`, `SDrain`, `SDecide` | Display dies (FIN queued behind `Ack(a)`); `link.close()` before the reader polls; assert a `display` death naming nothing acked, `a` not carried. Red on HEAD. Controls: `hub_record`, `hub_peek` (peek fails with an ack ahead of the FIN, always possible) |
| P9 display dies after the observation | `Die` after `SDrain` | Not a defect: the dial is captured as `hub`, once |
| P10 a stalled holder, a Hub end | `Block`, `HubReq`, `SURefuse`, `Timeout` | A handler blocks the listener; `link.close()` refuses writes and fails waiters at once, and after the bound the dial is captured as `hub` and redial is possible; the holder's later settle does nothing. Control: `defer_only` (deadlock) |
| P11 a stalled holder, a display or unresponsive end | `Block`, `RecEnd`, `SURefuse`, `Timeout` | The same behind a display end and behind an unresponsive end: after the bound the dial is captured with the recorded cause (`s2blk` set when an ack is unread, for either cause). Control: `timer_hub_only` (S1b) |
| P12 two capturers | `Timeout`, `SDecide`, `SettleGone` | Hold the listener in `SDrain..SDecide`, let the bound fire, release; one capture. Control: `s3_unguarded` (S3) |
| P13 a recorded cause is never overridden | `RecEnd`, `SDecide` | Record `unresponsive`, queue FIN; assert the capture says `unresponsive`. Control: `s4_overwrite` (S4) |
| P14 decode-error ends | `IBad`, `RBad` | A malformed frame with an ack behind it: the dial is captured as `display` undrained, once; `s2dec` is the bound, and S2 does not apply |
| P15 settle is idempotent and single | `SDecide`, `SettleGone` | Call `settle()` twice, and from the releaser and the listener at once; one capture |
| P16 the door is structural | `SettleGone` (listener unreachable) | Guard: `DisplayConnection` has no public method that captures; `Settler` is constructed only by `ReaderSlot`; the bound's capture is the one other site and is named. The refusal hands the asker a handle whose capture becomes enabled only after the bound has passed; a refusal that returned a `close_if_current`-shaped door would reopen it. Count references per qualified function across `src/punt_lux` recursively; plant bound-reference and `getattr` spellings |
| P17 a write completes after a Hub request | `WLock`, `WSendDone`, `HubReq`, `WOweOk`, `WUnlock`, `SDrain`, `SDecide` | Two threads, red first on the code at `d329c0aa`. Park `sendall` in `send_scene` behind a gate; on a second thread call `request_hub` (or `retire(gen, cause="hub")`); release the gate. Assert the settled cause is `hub`, no `DialDeath` is queued, the written scene is in the carry, and the writer raises `HubRetiredError`. Control: `writer_owe_refused` (S6), `writer_records_display` (S5 and S6) |
| P18 a write fails after a Hub request | `WSendDead`/`WSendTimeout`, `HubReq`, `WRec` | `sendall` raises after `request_hub`: assert no cause is recorded by the writer. A dead display (end of file queued) then settles as `display` by the drain's observation; a live one settles as `hub`. S5's writer clause (round 5); control `writer_split_record` for the race, P23 |
| P19 the drain waits for the writer | `WLock`, `DStartUnresp`, `RecEnd`, `SDrain` (guard `lk = fclear` or an unreadable socket), `WSendTimeout`/`WUnlock`, `SDecide` | Two threads. Hold the socket lock on thread B in a `sendall` stand-in; queue an ack; record `unresponsive`; settle on thread A. Release B within the send timeout. Assert the ack is applied and no death names it. Red first on the 0.25 s lock wait. Control: `drain_gives_up` (S2w) |
| P20 a writer that never releases, no asker | `WLock`, `WStall`, `DStartUnresp`, `RecEnd`, `SUGrant`, `SDrainLate`, `LateCapture`, `WStuckOut` | One settler that took the slot itself (no refused asker), the lock held past the ceiling (ceiling and bound shortened) with an ack readable. Assert the drain is `Drained(complete=False)` with a WARNING, the dial is captured by the bound, undrained (`s2lat`), with the recorded cause, `Settler.settle` afterwards does nothing, and the stuck writer is released by the capture's shutdown. The no-asker case is the point: rule 6 as an asker's timer does not apply. Since round 6 this is the way a settle ends behind a writer that keeps progressing (P30), and the defence for one that breaks its deadline. Control: `drain_no_late` (deadlock with no rescuer and the deadline broken; the progressing form is a livelock a deadlock check cannot see) |
| P21 the ack is owed after the capture | `WOweLate` | Capture the dial between `sendall` returning and `owe_ack`; assert `owe_ack` is refused (captured sink), the writer raises `ConnectionClosedError` (an `OSError`, so the replicator's recovery re-marks the scene for the next dial), the scene is in no ledger, and the dial charges nothing for it: the `a1late` under-charge, late by one dial. Also with a decode-error end in place of the capture |
| P22 the drain's look on an unreadable socket takes no lock | `SDrain` guard `sock = 0 & eof = fclear` | A writer holds the lock mid-send and nothing is readable: the drain returns at once, `complete=True`, without waiting for the writer |
| P23 the writer's check and record are one step (round 5) | `WSendTimeout`/`WSendDead`, `HubReq`, `WRec` | Red first on the two lock holds. Inject `request_hub()` between the write's failure and its record (wrap the writer-side entry); for `BlockingIOError` and `OSError`, assert the dial settles as `hub`, no death is queued, and the writer raises `HubRetiredError`. Control: `writer_split_record` (S5) |
| P24 a read that fails in the stop window asks for the Hub's end (round 5) | `SPStart`, `RReadErr`, `SDrain`, `SDecide` (never `SDecideNone`) | Red first on today's `_read`. Set the stop flag, make `poll_chunk` raise, run the reader: assert no `ValueError`, the dial settles as `hub`, no death; and a `send_scene` made in the window is refused. Control: `stop_no_request` (S0) |
| P25 a stalled write ends within `D` of no progress (round 6) | `WLock`, `WStall`, `Expire`, `WDeadline`, `WRec`, `SUGrant`, `SDrain` | A TLS peer that never reads: `send_scene` ends within `D` of its last progress (plus scheduling slack) as `unresponsive`, the writer raises its closed error, the cause is recorded once, and the dial settles. The plain-socket leg too, since the deadline is one path on both transports. Control: `unbounded_write` (no rescuer, deadlock) |
| P26 a ping or query behind a stalled writer ends the dial within `D` of no progress (round 6) | `DStartUnresp`, `Expire`, `KPing` (`prog = fclear`), `RecEnd` | Hold the socket lock on another thread with a writer stand-in that moves no byte; call `send_ping` and `send_query`: each ends within `D` of the socket's last progress, the dial records `unresponsive` once, and a settle follows. Control: `unbounded_write` (no rescuer, deadlock) |
| P27 the keepalive's ping, or a query, is the first write to stall (round 6) | `DStartUnresp`, `KPing` (its write bounded by the same no-progress `D`), `RecEnd` | A TLS peer that never reads, no scene in flight: the keepalive's ping takes the free lock and its write stalls; it ends within `D` of the socket's last progress, the dial records `unresponsive` once, and the lock is released. The same with a query in the ping's place. No control in the model: `KPing` is one step, sound only under this obligation |
| P28 the bound records `hub` over a pending request, never its asker's cause (round 6) | `HubReq`, `WRec` (refused), `SURefuse`, `Timeout` | Red first on `BoundedAsk.settle_by_bound` calling `generation.end(cause)`. A listening dial whose listener holds the slot past a shortened bound; a Hub request; then a writer failure: the writer's record is refused, it asks, waits the bound, and captures. Assert the dial settles as `hub` and no death is queued. The same through the keepalive's verdict in the writer's place. Control: `bound_records_asker` (S5, A3) |
| P29 a write that keeps progressing is never cut short (round 6) | `WLock`, `WProg`, `WStall`, `WSendDone`, `WOweOk` (no `WDeadline`, no `KPing` while `prog = fset`) | Red first on round 5's whole-write deadline. A TLS (and a plain) peer that drains slowly but steadily, so the write takes several times `D` with no gap of `D`: `send_scene` completes, the scene is in the ledger, no end is recorded, and the display is not reaped. Control: `whole_write_deadline` (S7, the writer's verdict). The keepalive's side is P31 |
| P30 a settle behind a writer that keeps progressing ends by the late path (round 6) | `WLock`, `WProg`, `WStall`, `RecEnd`, `SUGrant`, `SDrainLate`, `LateCapture`, `WStuckOut` | A writer that keeps progressing past the ceiling (ceiling and bound shortened); end the dial and settle with no refused asker: the drain is incomplete with a WARNING, the dial is captured by the bound within ceiling plus bound, and the capture's shutdown ends the writer, which raises. Control: `drain_no_late` (its progressing form is a livelock, so the witness is the stalled form with the deadline broken) |
| P31 the keepalive gives no verdict within `D` of progress in either direction (round 6) | `DStartUnresp`, `KPing`, `WSendDone`, `Ack` (the code's last-progress time, which the model's `prog` approximates only for an outgoing byte while a writer holds the lock) | Red first on a keepalive that times its own ping, or reads only outgoing progress. Three cases, each with the keepalive's verdict due: a write that completed less than `D` ago and no byte since; an incoming ack less than `D` ago and no outgoing byte for longer than `D`; a write still progressing. Assert no `unresponsive` end is recorded in any of them, and that one is recorded once `D` passes with no byte either way. No control in the model: the model's `KPing` fires early in the first two cases (the superset of `Stp`), so S7's keepalive clause is an obligation on the code, and this test is its only guard |

## Test mapping

Tests are in `tests/domain/test_dial_settlement.py` unless a file is named. The `DialEnd` unit
tests (`tests/domain/test_dial_end.py`) cover the first-wins record and the Hub request that
the partitions rest on: `TestRecording`, `TestTheHubsRequest`, `TestDeciding`,
`TestTheSinkThatOwnsOne`. The drain's routing is covered by `tests/domain/test_dial_drain.py`
(`TestWhatTheDrainRoutes`, `TestWhatTheDrainSurvives`, `TestASkewedAckLeavesTheLedgerWhole`,
`TestACutShortDrainSaysSo`).

| Partition | Test |
|-----------|------|
| P1 | `TestAStartThatFails::test_p1_a_dial_ended_before_its_reader_started_is_settled_by_the_release` |
| P2 | `TestAStartThatFails::test_p2_a_thread_that_cannot_start_leaves_the_slot_free_and_the_dial_gone` |
| P3 | `TestARecordThatLandsInTheSettle::test_p3_the_listener_that_stops_drains_again_before_it_captures` |
| P4 | `TestAnInlineHolderPastItsLastCheck::test_p4_an_end_that_lands_before_the_release_is_settled_by_it` |
| P5 | `TestTheCriticalSections::test_p5_a_refusal_and_its_debt_are_one_critical_section` |
| P6 | `TestTheCriticalSections::test_p6_a_release_and_its_debt_read_are_one_critical_section` |
| P7 | `TestARecordThatLandsInTheSettle::test_p7_a_settle_with_no_reader_drains_again_before_it_captures` |
| P8 | `TestADisplayThatDiesBeforeTheHubEndIsDecided::test_p8_a_display_dead_with_its_ack_ahead_of_the_end_is_the_displays_end`; `::test_p8_a_display_dead_before_it_acked_is_charged_for_the_scene` |
| P9 | `TestADisplayThatDiesBeforeTheHubEndIsDecided::test_p9_a_live_display_asked_to_end_is_the_hubs_end_and_carries_its_scene` |
| P10 | `TestAStalledHolder::test_p10_a_hub_end_refuses_at_once_and_is_captured_by_the_bound` |
| P11 | `TestAStalledHolder::test_p11_a_recorded_end_is_captured_by_the_bound_with_its_cause` |
| P12 | `TestAStalledHolder::test_p12_the_holders_settle_after_the_bound_captured_is_not_a_second_capture` |
| P13 | `TestASettleIsOneAndAnEndIsTheFirstRecorded::test_p13_a_recorded_cause_is_never_overridden_by_what_the_drain_sees` |
| P14 | `TestASettleIsOneAndAnEndIsTheFirstRecorded::test_p14_a_frame_that_cannot_be_decoded_ends_the_dial_undrained` |
| P15 | `TestASettleIsOneAndAnEndIsTheFirstRecorded::test_p15_a_settle_made_twice_or_at_once_captures_once` |
| P16 | `tests/domain/test_settlement_door.py`: `TestTheDoorIsTheSlot` (`test_a_settler_is_made_only_by_the_reader_slot`, `test_a_bounded_ask_is_made_only_by_the_reader_slots_refusal`, `test_a_dial_is_marked_closed_and_shut_only_by_the_connections_capture`, `test_the_capture_reaches_only_the_slot_its_settler_and_the_bound`, `test_the_doors_the_design_removed_are_referred_to_nowhere`); `TestTheGuardCanFail` (`test_every_spelling_of_a_second_door_is_counted`, `test_a_type_or_a_plain_import_is_not_a_reference`, `test_references_are_keyed_by_the_qualified_function`) |
| P17 | `TestTheWriter::test_p17_a_write_that_completes_after_a_hub_request_is_owed_and_carried` (two threads) |
| P18 | `TestTheWriter::test_p18_a_write_that_fails_after_a_hub_request_records_no_cause`, parametrized over a dead and a live display: the dead one settles as `display`, the live one as `hub`, and nothing is charged |
| P19 | `TestTheWriter::test_p19_a_drain_waits_for_the_writer_that_holds_the_socket_lock` (two threads; asserts the waiting settler holds neither the state lock nor the sink's) |
| P20 | `TestTheWriter::test_p20_a_writer_that_never_releases_is_captured_by_the_bound_and_the_drain_says_incomplete` (no refused asker; a later `Settler.settle` returns `False` and drains nothing) and `::test_p20_the_captures_shutdown_wakes_a_writer_stuck_in_sendall` (the capture's shutdown ends the stuck write) |
| P21 | `TestTheWriter::test_p21_an_ack_owed_after_the_capture_is_refused_not_recorded` and `::test_p21_a_scene_refused_after_the_capture_is_re_marked_for_the_next_dial`, parametrized over a capture and a decode error |
| P22 | `TestTheWriter::test_p22_a_drain_of_an_unreadable_socket_does_not_wait_for_the_writer` |
| P23 | `TestTheWriter::test_a1_a_hub_request_landing_before_the_writers_record_wins`, parametrized over `BlockingIOError` and `OSError`; and `tests/domain/test_retire_cause.py::TestAHubRetireThatLandsBetweenTheCheckAndTheRetire::test_a_write_that_loses_the_retire_reports_the_hubs_cause_and_queues_nothing` |
| P24 | `TestTheWriter::test_a2_a_read_failing_while_the_reader_is_stopped_requests_the_hub_end` (no `ValueError`, settles as `hub`, no death, and a `send_scene` made in the window is refused) |
| P25 | `tests/domain/test_tls_generation.py::TestABoundedWrite::test_p25_a_tls_peer_that_never_reads_ends_the_write_within_the_deadline`; `tests/domain/test_dial_settlement.py::TestABoundedWrite::test_p25_a_plain_socket_write_ends_within_the_same_deadline` and `::test_p25_a_write_the_deadline_cut_half_way_ends_the_dial_unresponsive`. **GAP**: no test asserts the cause is recorded once. **Contradicts round 6**: `test_tls_generation.py::TestABoundedWrite::test_p25_a_slow_draining_tls_peer_ends_the_write_within_the_deadline` asserts the whole-write rule that `whole_write_deadline` refutes; it becomes P29's test, inverted. All P25 bounds are to be measured from the last progress, not the start |
| P26 | `tests/domain/test_dial_settlement.py::TestABoundedWrite::test_p26_a_ping_or_query_that_cannot_take_the_socket_lock_ends_the_dial_unresponsive`, parametrized over a ping and a query; under round 6 its stand-in writer must move no byte, and its bound is `D` of no progress |
| P27 | `tests/domain/test_tls_generation.py::TestABoundedWrite::test_p25_a_keepalive_ping_that_is_the_first_write_to_stall_ends_the_dial`, to be renamed `test_p27_...`. **GAP**: no test for a query as the first write to stall (`::test_p27_a_query_that_is_the_first_write_to_stall_ends_the_dial`), and none asserts the cause is recorded once or the lock released |
| P28 | **GAP**: `tests/domain/test_dial_settlement.py::TestTheBound::test_p28_a_bound_past_a_hub_request_settles_as_hub_whoever_asked`, parametrized over a writer and the keepalive as the asker |
| P29 | **GAP**: `tests/domain/test_tls_generation.py::TestABoundedWrite::test_p29_a_slow_but_steady_tls_peer_keeps_its_write` and `tests/domain/test_dial_settlement.py::TestABoundedWrite::test_p29_a_slow_but_steady_plain_peer_keeps_its_write`. The keepalive's assertion, formerly `test_p29_the_keepalive_gives_no_verdict_while_bytes_move`, is folded into P31 |
| P30 | **GAP**: `tests/domain/test_dial_settlement.py::TestTheWriter::test_p30_a_settle_behind_a_writer_that_keeps_progressing_ends_by_the_late_path` |
| P31 | **GAP**: `tests/domain/test_dial_settlement.py::TestABoundedWrite::test_p31_the_keepalive_gives_no_verdict_while_bytes_move_either_way`, parametrized over a completed write, an incoming ack and a write still progressing, plus `::test_p31_the_keepalive_gives_its_verdict_once_d_passes_with_no_byte_either_way` |

Every test named above is on this branch. P28 to P31 have no tests yet; their names are the
ones the round-12 contract is to use, each red first. The model is the code as built, plus the
round-6 rules: the drain waits for the lock to the ceiling, reports itself incomplete, and the
settler hands the capture to the bound; the writer's record is atomic; a reader stopped in the
window asks for the Hub's end; the bound records `hub`, never its asker's cause, over a pending
request; and every write and every lock wait ends within `D` of no progress, never `D` of
elapsed time.

## Not modelled

A second discoverer, a second inline reader, more than one unread acknowledgement,
`end_stream(hub)` (a reply nobody was owed; it records `hub` at once, nothing can be read past
a skewed stream, and a hub capture charges nothing), and send timeouts (rmh).

## Obligations the model cannot see (for the implementation contract)

The model's actors are always distinct threads and always on one host. Three obligations
follow from outside it; the implementation contract cites them by number.

1. **The asker on the holder's thread does not wait.** An interaction handler runs on the
   listener thread; a write that fails there calls `_write_failed`, `retire(display)`, then
   the slot's `ask_settle` with the slot held by that same thread (a refusal hands back a
   `BoundedAsk`, whose `may_wait=False` on that thread leaves a debt only). Waiting out the bound there
   captures undrained after 2 s, where returning would have drained and settled one step
   later. Its refusal's debt is enough: it is the holder and settles on return. The wait runs
   holding no lock that the holder's settle takes (the socket lock, `st`, the slot's
   condition). State the worst case on a Hub end: `ListenerThread.stop` takes up to the bound,
   then up to the join.
2. **The end of file the drain observes includes a reset and a TLS EOF.** On Linux `AF_UNIX`
   a peer that closes with data it has not read (a Hub frame still in the display's receive
   queue) gives the survivor `ECONNRESET` after the queued bytes, not EOF. A byte queued toward
   the Hub is ordinary data followed by a plain EOF. `DialSocket.drain` reports a reset, a
   broken pipe, a TLS end of file or any failed read as `Drained(b"", ended=True)`, with a
   DEBUG line for a stream end and a WARNING otherwise, so the settler is told an end was
   seen. A drain that were to report a cut-short read as "nothing more" would fail S5 in the
   code with the model green.
3. **The complete drain is a same-host claim.** An RST from a process that dies with unread
   input may discard what was queued, so on TCP a dead display's drain is not complete. The
   claim that the drain is complete is restricted to same-host sockets, and that restriction
   is the contract; a cross-host end is outside it.

Test rows: for 1, a handler on the listener thread fails a write on a held slot and the dial
is drained and settled on return, not captured at the bound; for 2, the Hub sends a frame
the display does not read, the display queues an ack toward the Hub and closes, and the Hub's
drain must read the ack and then report an end on `ECONNRESET`, over both `AF_UNIX` and TLS (a
byte queued toward the Hub behind the ack gives a plain EOF and does not exercise the reset);
for 3, a test that a drain over TCP is not claimed complete, or that the cross-host path is
not routed through the complete-drain rule.

Tests for the obligations:

| Obligation | Test |
|------------|------|
| 1 asker on the holder's thread | `TestAnAskerOnTheHoldersOwnThread::test_the_listeners_own_failed_write_is_settled_on_its_return_not_at_the_bound`; `::test_an_inline_holders_own_ask_leaves_a_debt_and_never_waits` |
| 2 end of file includes a reset | `TestTheEndOfAStreamTheDrainSees::test_a_reset_that_follows_queued_acks_is_the_displays_end` (`AF_UNIX`); `::test_a_plain_end_of_file_is_the_displays_end`. The TLS legs are covered in `tests/domain/test_tls_generation.py`: `test_a_tls_end_of_file_that_follows_queued_acks_is_read_then_the_displays_end` (a clean close yields a ragged EOF, and the ack is read before the end) and `test_a_tls_reset_is_the_displays_end_though_it_may_discard_a_queued_ack` (a reset can drop a queued ack, even on Linux loopback). The `AF_UNIX` leg is complete: a same-host reset delivers what was queued. The TLS reset leg may lose a queued ack, which is the same-host-only claim of obligation 3: TLS is the cross-host transport, and a cross-host end is outside the complete-drain contract |
| 2 send timeout (F5) | `TestASendThatTimesOut::test_f5_a_send_timeout_is_recorded_unresponsive_not_the_displays_death` |
| 3 same-host claim only | `tests/domain/test_dial_drain.py::TestTheDrainClaimsCompletenessForSameHostSocketsOnly::test_the_contract_is_stated_where_the_drain_is_defined` (asserts the stated contract; it does not exercise a TCP drain) |
| drain wedge on TLS | `tests/domain/test_tls_generation.py::test_retiring_a_dial_releases_a_sender_wedged_on_a_tls_socket` |

## Controls

All in `docs/`, each `dial_settlement_<name>_buggy.tex`: `start_fail`, `stop_skip_drain`,
`inline_strand`, `split_settle`, `atomic_refuse`, `atomic_release`, `defer_only`,
`timer_hub_only`, `s3_unguarded`, `s4_overwrite`, `hub_record`, `hub_peek`, and (round 4,
against the file with the writer) `writer_owe_refused` (one point: the refused ack; S6),
`writer_records_display` (today's code, two changes: the refused ack and a classification that
ignores a Hub request; S5 and S6), `drain_gives_up` (one point in `SDrain`; S2) and
`drain_no_late` (one point: `SDrainLate` removed; behind a writer that stalls it is a defence
control, wedging only when the write deadline is also broken, and since round 6 behind a writer
that keeps progressing `SDrainLate` is the only way the settle ends; that form is a livelock a
deadlock check cannot see, so its witness is the deadlock with no rescuer and `WDeadline`
disabled), and (round 5) `writer_split_record` (one point: the check and the record under two
lock holds; S5), `stop_no_request` (one point: a read failing in the stop window asks for
nothing; S0) and `unbounded_write` (the code before round 5, two changes: no write deadline and
a keepalive that waits for the lock and knows no progress; deadlock with no rescuer, and neither
change alone deadlocks), and (round 6) `bound_records_asker` (one point: past the bound the
asker records its own cause over a pending request; S5, A3) and `whole_write_deadline` (one
point: the deadline counts elapsed time for the whole write, at both its sites; S7; a
control-only local, `rdb`, records whether bytes moved since the write began, for the flag;
it is observation only, read by no guard, and it is the right condition because at a
whole-write deadline, `D` after the start, "a byte within `D`" is "a byte since the start";
flagging `prog = fset` instead finds `WLock, WSendTimeout`, a deadline at time zero; the
reported witness is realisable: a start at 0, a byte at 2.0 s, the deadline at 2.5 s). All
nine writer controls are rebuilt from the round-6 design and re-run on it, except
`writer_owe_refused`'s exhaustive run showing it never reaches `s5bad` (round 4, 2619753 states).
That result stands by a direct argument, not by the one that carries found traces forward: only
`WRec` sets `s5bad` in the design, and it records, so flags, only with no cause and no request;
the refused ack, the control's one source of a `display` for a live display, is enabled only with
a cause or a request, and neither clears while the dial is current; and no step added since sets
`s5bad` in the design. The first twelve were committed against the round-3 file, which had no
writer; they are one-point mutations of it. They still stand: with the writer idle
(`pc(aWr) = pidle`, `lk = fclear`, so `prog` is never set) and `KPing` inserted after each
`DStartUnresp`, every round-3 trace is a round-6 trace (the actor sets only grew, the drain lost
a guard, and `SPStart` also sets a flag nothing in those traces reads), and the flags never
clear, so each control's violation remains reachable in the round-6 file. No re-run is needed. The earlier
`hub_peek_sock0` result (peek sound with an empty buffer) is withdrawn: with a living display
that can ack and then die, the peek is unsound from any initial state.
