# Dial settlement: coverage audit

Companion to [dial_settlement.tex](./dial_settlement.tex) and its three controls.
It lists the partitions of the model and the tests that must cover them. No test
here exists yet: the implementation follows the model. Each row names the test that
must be red on the code as it stands at `41e90082` and green on the design.

Governs: `src/punt_lux/domain/hub/{display_connection,dial_reader,display_listener,
listener_thread,display_replies,reply_sink,dial_generation,reader_slot,dial_drain}.py`.
Re-run `fuzz`, the model-check and the three controls whenever the end, settle or slot
paths change.

## The properties

| Id | Claim | Model check |
|----|-------|-------------|
| S1 | An ended or end-requested current dial is always settled by a party already running | wedge goal, and the deadlock check: not found / none (8080 states) |
| S2 | A display or unresponsive end is captured only after the drain | `s2bad`: not found |
| S3 | One capture per dial | `s3bad`: not found (holds by the `current` edge; the flag checks it) |
| S4 | The captured cause is the first recorded | `s4bad`: not found (structural; one writer of `ended`) |
| S5 | A display already dead is never recorded as a Hub end | `s5bad`: not found; reachable in the code's own `retire(hub)` |

## The design the model proves

One rule: settlement belongs to the holder of the reader slot; everyone else asks.

1. **The door is the slot.** `close_if_current` is removed from `DisplayConnection`'s
   interface. `ReaderSlot` hands its holder a `Settler` (the listener thread gets it from the
   born-holding slot or `claim_for_listener`; an inline reader from `inline()`; a releaser
   taking over gets it from `release`). `Settler.settle()` is the only code that
   captures. No `by_reader` flag exists. The model's uncovered `RSettleGone`
   is this claim: while the listener holds the slot nobody else captures.
2. **Ends record or request.** `retire(display|unresponsive)` records the cause (first wins).
   `retire(hub)` sets `hubreq` and records nothing. Both then call the no-reader settle.
3. **A refusal leaves a debt, atomically.** `settle_unread` under the slot's condition lock:
   free, take it; held, set `debt`. The release reads and clears `debt` under the same lock.
4. **A release honours the debt.** `release_listener`, the inline exit and the start failure
   all release through one method that, on a debt, keeps the slot, settles, and looks again.
   `start_on` on a dial found ended releases the slot before it raises.
5. **Settle reads the cause once.** It drains to the point of blocking, then the outcome
   decides: end of file is `display`; else a pending `hubreq` is `hub`; else the recorded
   cause stands. The listener's exit on its stop flag runs this step and records
   nothing itself.

The code as it stands cannot meet S1 to S5 without rule 1 and rule 2. Three patches
(release in `start_on`, re-check after the inline release, record before the read) close the
three round-9 traces but leave S5 open and keep `by_reader` a default.

## Partitions

| Partition | Model operations | Test (two threads where stated) |
|-----------|------------------|-------------------------------|
| P1 start fails on an ended dial | `StFail`, `StRel0`, `HubReq`, `SURefuse`/`SUGrant` | Hold `open_as_hub` between `open_listening` and `start_on`; end G2 on thread B (`_write_failed`); release A. Assert G2 not current, one `DialDeath(display)` with G2's owed scenes, the next `asks()` redials. Red on HEAD. Control: `start_fail_buggy` |
| P2 start fails on a healthy dial (thread cannot start) | `StFail` with `current` | Make `Thread.start` raise; assert the slot is free, then `retire(hub)` settles synchronously and the dial is not current |
| P3 stop exits on its flag, display end lands in the window | `RNotice`, `RSettleCap`, `SPStart`, `HubReq`, `RecEnd` | Wrap `DialDrain.run` so that when entered on a dial with no cause, `end("display")` lands first; send `a`, queue `Ack(a)`, `link.close()`; assert no death names `a`. Reverting to two reads is red. Control: `stop_skip_drain_buggy` |
| P4 inline holder past its last check | `IAcq`, `ILastSkip`, `RecEnd`, `SURefuse`, `RelOwes`/`RelFree` | Hold A between `_settle_if_ended` and the slot release (wrap the `inline()` exit); fail a write on B; release A. Assert `not link.is_connected` and the death is queued. Red on HEAD. Control: `inline_strand_buggy` |
| P5 refusal and release are one critical section | `SURefuse`, `RelOwes`, `RelFree` | Deterministic: instrument the slot's lock; refuse between A's debt read and A's release. The refuser finds the slot free |
| P6 display dies before the Hub's end is decided | `Die`, `SPStart`, `HubReq`, `SettleCap` | Display dies (FIN queued behind `Ack(a)`); `link.close()` before the reader polls; assert a `display` death naming nothing acked, and `a` not carried. Red on HEAD. The peek variant fails this (acks hide the FIN): add the case with the ack queued |
| P7 display dies after the observation | `Die` after `SettleCap` | Not a defect: assert the dial is captured as `hub`, once |
| P8 settle is idempotent and single | `SettleCap`, `SettleGone` | Call `settle()` twice, and from the releaser and the reader at once; one capture |
| P9 the door is structural | (uncovered `RSettleGone`) | Guard: `DisplayConnection` has no public method that captures; `Settler` is constructed only by `ReaderSlot`; bound-reference and `getattr` spellings are planted. Count references per qualified function across `src/punt_lux` recursively |
| P10 hub end while the listener is in a handler | `HubReq`, `RNotice` | A handler blocks the listener; `link.close()` returns; the dial settles within one poll after the handler returns. The model's S1 only needs eventually; assert the bound |
| P11 end-stream (reply out of order) | not modelled | Keeps recording `hub` at once, because nothing can be drained: add a test that it never carries `display` |

## Not modelled

A second discoverer, a second inline reader, more than one unread acknowledgement,
decode-error ends. The design needs the refusal-and-debt and the release-and-debt-read
each to be one critical section (P5); with that the debt is a flag and settle is idempotent.

## Scratch controls for S5 (not committed: outside the mission's write set)

In `.tmp/missions/results-model-settle/`: `dial_settlement_hub_record_f5.tex` (the code's
`retire(hub)` recording at once: `s5bad` in 3 steps), `dial_settlement_hub_peek_f5.tex`
(peek without drain: `s5bad` in 3 steps with an ack ahead of the FIN),
`dial_settlement_hub_peek_sock0.tex` (peek with an empty buffer: not found, 9154 states).
They should join `docs/` as `_buggy` controls if the design is accepted.
