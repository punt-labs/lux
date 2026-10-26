# Dial settlement: coverage audit

Companion to [dial_settlement.tex](./dial_settlement.tex) and its controls. It lists the
partitions of the model and the tests that must cover them. No test here exists yet: the
implementation follows the model. Each row names the test that must be red on the code as
it stands at `41e90082` and green on the design.

Governs: `src/punt_lux/domain/hub/{display_connection,dial_reader,display_listener,
listener_thread,display_replies,reply_sink,dial_generation,reader_slot,dial_drain}.py`.
Re-run `fuzz`, the model-check and every control whenever the end, settle or slot paths
change.

## The properties

| Id | Claim | Status |
|----|-------|--------|
| S1a | An ended or end-requested current dial is settled by a party already running, with no timer. Holds only if the three atomicity obligations hold; broken, the dial degrades to the 2 s bound and an undrained capture | checked: goal not found (90905 states, `-bf`); every round-9 control trips it |
| S1b | The same behind a holder that never makes progress, by the bound | checked: goal not found; `defer_only` deadlocks, `timer_hub_only` trips the goal |
| S2 | A dead display's end is captured only after a drain that began after it was recorded | checked: `s2bad` not found; `split_settle` and `stop_skip_drain` trip it |
| S3 | One capture per dial | **structural** (every capture guarded by `current`); `s3_unguarded` trips it |
| S4 | The captured cause is the first recorded | **structural** (one first-wins writer); `s4_overwrite` trips it |
| S5 | A display dead when observed is never recorded as hub | **structural** (the cause is a function of the observation); `hub_record` and `hub_peek` trip it |

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
sent). That is enough for A1 and A2. Four paths have no abstract counterpart and are
deliberate exceptions to A1 or A2, each with its bound:

| Exception | Flag | Fails | Bound |
|-----------|------|-------|-------|
| a display charge with an ack unread, from a broken stream | `s2dec` | A2 | the acks behind the bad frame, once |
| the bound's capture of a display end | `s2blk` | A2 | every ack queued while the holder stalled, after 2 s |
| the bound's capture of an unresponsive end | `s2blk` | A2 | as above; flagged since round 3 |
| `hub` recorded by the bound for a display already dead | `s5blk` | A1 | a poison death is carried and not charged; a later ack read clears it; after 2 s, once |

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

The code as it stands cannot meet S1 to S5 without rules 1, 2 and 6. Patching the three
round-9 traces (release in `start_on`, re-check after the inline release, record before the
read) leaves S5 open, leaves `by_reader` a default, and leaves the Hub end's escape from a
stalled holder missing.

## Partitions

| Partition | Model operations | Test (two threads where stated) |
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

## Not modelled

A second discoverer, a second inline reader, more than one unread acknowledgement,
`end_stream(hub)` (a reply nobody was owed; it records `hub` at once, nothing can be read past
a skewed stream, and a hub capture charges nothing), and send timeouts (rmh).

## Obligations the model cannot see (for the implementation contract)

The model's actors are always distinct threads and always on one host. Three obligations
follow from outside it; the implementation contract cites them by number.

1. **The asker on the holder's thread does not wait.** An interaction handler runs on the
   listener thread; a write that fails there calls `_write_failed`, `retire(display)`, then
   `settle_unread` with the slot held by that same thread. Waiting out the bound there
   captures undrained after 2 s, where returning would have drained and settled one step
   later. Its refusal's debt is enough: it is the holder and settles on return. The wait runs
   holding no lock that the holder's settle takes (the socket lock, `st`, the slot's
   condition). State the worst case on a Hub end: `ListenerThread.stop` takes up to the bound,
   then up to the join.
2. **The end of file the drain observes includes a reset and a TLS EOF.** On Linux `AF_UNIX`
   a peer that closes with unread data gives the survivor `ECONNRESET` after the queued bytes,
   not EOF. `DialSocket.drain` returns `None` on a cut-short read and does not say that an end
   was seen (`dial_socket.py:173-176`); the settler must be told. Otherwise S5 fails in the
   code with the model green.
3. **A cross-host reset is a bound.** An RST from a process that dies with unread input may
   discard what was queued, so on TCP a dead display's drain is not complete. State the case
   as a bound beside B3, or restrict the complete-drain claim to the same host.

Test rows: for 1, a handler on the listener thread fails a write on a held slot and the dial
is drained and settled on return, not captured at the bound; for 2, a peer that closes with
an unread byte queued behind the last ack gives a drain that reports an end, over both
`AF_UNIX` and TLS; for 3, the same over TCP, asserting the stated bound.

## Controls

All in `docs/`, each `dial_settlement_<name>_buggy.tex`: `start_fail`, `stop_skip_drain`,
`inline_strand`, `split_settle`, `atomic_refuse`, `atomic_release`, `defer_only`,
`timer_hub_only`, `s3_unguarded`, `s4_overwrite`, `hub_record`, `hub_peek`. The earlier
`hub_peek_sock0` result (peek sound with an empty buffer) is withdrawn: with a living display
that can ack and then die, the peek is unsound from any initial state.
