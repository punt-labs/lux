# Crash attribution: model results and coverage audit

Spec: [crash_attribution.tex](./crash_attribution.tex). Fidelity controls:
[ack_on_receipt](./crash_attribution_ack_on_receipt_buggy.tex) (the code before T11),
[no_carry](./crash_attribution_no_carry_buggy.tex) (T11 without T12, through both the
Hub's retire and the probe's),
[unresponsive_no_carry](./crash_attribution_unresponsive_no_carry_buggy.tex) (only the
unresponsive door's carry removed),
[inflight_ack](./crash_attribution_inflight_ack_buggy.tex) (capture without the split-read
guard), and the four T10-era controls regenerated against this specification
([redial_only](./crash_attribution_redial_only_buggy.tex),
[idle_stop](./crash_attribution_idle_stop_buggy.tex),
[hub_end_charged](./crash_attribution_hub_end_charged_buggy.tex),
[double_charge](./crash_attribution_double_charge_buggy.tex)). Design variant:
[inflight_ack_drain](./crash_attribution_inflight_ack_drain.tex).
Governs `src/punt_lux/domain/hub/{batch_sender,recovery,display_connection,
dial_generation,dial_socket,dial_drain,dial_reader,display_listener,display_replies,
listener_thread,reply_sink,reader_slot,settler,bounded_ask,dial_end,settlement,
suspect_book,death_queue,death_charger,dial_death,liveness_probe,replicator}.py` and the display's held ack in
`src/punt_lux/display/client_sender.py` (its release, after a completed swap, in
`src/punt_lux/display/frame_turn.py`; its hold in
`src/punt_lux/display/render_loop.py`).

Rulings modelled:

- **T10**: the death of a dial is charged from that dial's own ack ledger, whoever
  discovers it; a Hub-ended dial and an empty ledger charge nothing.
- **T11**: the ack means a frame survived the scene. The display installs a scene on
  receipt, holds its ack, and after the next completed buffer swap sends every held ack,
  in receipt order, whether or not the scene was visible.
- **T12**: when a Hub-ended dial settles with a non-empty ledger, that ledger joins a
  carried suspect set. Reading any ack on any later dial clears it. A display-ended death
  charges its own ledger together with the carried set, then clears the carried set.
  Each death is queued at discovery, handed over once, and charged first at the
  replicator's next push or idle tick, before the quarantine filter. The queue has no
  silent bound.
- **T13**: a third retire cause, `unresponsive`, for a dial the keepalive or the isolation
  probe gives up on while the display may still be alive (`clients.drop_unresponsive`). It
  queues the dial's suspects for charging, as a display death does, and also carries
  them, as a Hub end does, because the display may outlive the dial.
- **T14**: the read of an ack is two steps, `Recv` (bytes taken off the socket) and
  `Deliver` (frame applied to the ledger). A display-ended or unresponsive capture is taken
  by the dial's own reader, after a non-blocking drain of the socket and after delivering
  every complete frame, and before `shut()`. The model guards the capture on both the
  socket and the reader's buffer being empty.

Origin: the recurrence of attribution defects in final review rounds 4 to 7
(`review-r6-silent.md` F1, `review-r6-code.md` F1, `review-r7-silent.md` F1 and F3 to F5,
`review-r7-invariants.md` F-3 to F-6 and F-9, `eval-gvr-r1.md` M1) and the evaluation of
this model (`eval-jra-r1.md`, F1 to F8).

## Invariants (negated goals; never schema conjuncts)

| Id | Statement | By |
|---|---|---|
| A1 | Every poison death observed on a live dial is, once settled and no longer queued, charged to the poison scene (own ledger or carried set), whichever party discovered it, across Hub-ended and unresponsive dials and while the replicator is away. A1w: the wrong scene is charged in its place | the settle of the dead dial queues its suspects once, at discovery, in the hold that retires it; `take_deaths` hands the queue out once (a capability, as the write seat is); the one replicator charges it first at its next push or idle tick, before the quarantine filter; the carried set rides in the death |
| A2 | No scene is charged for a death of a display this Hub was attached to unless it was in that death. Per write, not per scene id: an acked earlier write of a scene does not clear a later, unacked one. Own ledger: a scene written to the dial whose ack the display did not send (an ack in flight, or taken off the socket and not applied, counts as sent). Carried set: a scene written to an earlier Hub-ended or unresponsive dial, with no ack applied and no display-ended death since | ledger = written minus acked, captured by the reader after the drain; carried set = Hub-ended and unresponsive ledgers since the last applied ack |
| A3 | A Hub-ended dial charges no scene (its ledger is carried, which is not a charge). An unresponsive dial is the display's end for DES-102 and does charge | queue only when `cause` is `display` or `unresponsive`; a Hub-ended retire appends to the carried set |
| A4 | Each dial's death is charged at most once | the capture succeeds once per generation, under the state lock; a death is popped from the queue once, and one whose charge failed goes back at the head |

A3 and A4 are tautologies of the fixed design; their content is the guards. The A1 row's
"By" is the code's mechanism, not the model's: in the model a discovery enqueues and a
separate step charges, which is the code's shape. What holds A1's timing is an ordering
argument, not a guard: a scene re-marked dirty by a redial is sent only by a push, and a
push charges before it filters. That holds only because the replicator is the one sender
and the one charger; a second charger, or a send path that skips the charge-first step,
breaks it (obligation O1).

A1 is a safety property: a death that stayed queued for ever would satisfy it. The model
has the liveness too, by acyclicity: `PushStart` needs an empty queue, every other step
consumes a finite resource, and deadlock-freedom is checked, so every maximal run reaches
`Charge` for each queued death. A stalled charger breaks exactly this; the idle tick must
keep charging (O1).

The model abstracts writes to scene ids: a scene is written at most once per dial, while the
code rewrites a scene on the same dial when it changes and keeps a positional queue of
writes (`reply_sink.py`). The refinement is sound, because a scene id is a suspect while any
of its writes is unacked, and A2 is read per write.

## What the model found

1. **T11 alone is unsound (the counterexample).** A scene installed and held on dial 1
   survives the Hub's retirement of dial 1. The display crashes painting it on dial 2. Dial
   2's ledger holds only the scenes written to dial 2, so the culprit is charged on no
   ledger and an innocent scene takes the strike. Reproduced by `no_carry`; closed by T12.
2. **The same loss through the probe's door (T13).** The keepalive and the isolation probe
   retire a dial with the display still alive (`drop_unresponsive`). The model first had no
   such step; with it, and with the retire queued but not carried, A1w is violated (`no_carry`,
   6,546 states). Carrying an unresponsive dial's suspects, as well as queueing them,
   closes it. `no_carry` shows both doors; a scratch control that removes only the
   unresponsive door's carry shows the second alone.
3. **T12 and T13 are sound in the model.** A1 to A4 hold for the design at 2 dials, 2 scenes
   (30,883 states), at 3 dials, 2 scenes (2,143,829 states) and at 2 dials, 3 scenes
   (718,209 states), with no deadlock.
4. **The in-flight ack is a real hazard, and "read the socket to end of file" does not
   discharge it.** The display acks a scene at a swap and dies; the Hub's reader has taken
   the ack off the socket and not applied it; a non-reader (the replicator's `EPIPE`, the
   keepalive) retires the dial; the socket is empty, so reading it finds nothing, and the
   scene is charged although the display sent its ack and the Hub received it
   (`inflight_ack`: A2 violated in 2,347 states; with no guard at all, 1,161). The guard
   must be on the reader's own buffer. **The model supports the drain as T14 words it**:
   the dial's own reader drains the socket without blocking, delivers every complete frame,
   and only then takes the ledger, before `shut()`. A non-reader discoverer signals and does
   not capture (a dial has one reader). Whether the guard is a precondition on the capture
   (the design) or the drain is part of it (`inflight_ack_drain`) does not matter to the
   goals; both have 30,883 states. The alternative, to say in DES-102 that "acked" means
   "acks the Hub had applied", leaves A2 violated and is not recommended. For a cross-host
   transport, bytes still in flight on the network remain a residual over-charge.
5. **The swap stall: A2 survives; precision does not.** If the display stops completing
   swaps, every scene received since the last swap stays held and unacked, and a later
   death charges all of them: A2 still holds (nothing outside the dial's ledger and the
   carried set is charged). The bound is the number of scenes written to that dial since
   its last applied ack, plus the carried set. An innocent scene is quarantined only if it
   was a suspect at `thr` deaths (reachable: `strikes(2) = 2`). In isolation the stall
   blocks the next send until the isolation probe's timeout retires the dial as
   unresponsive: its ledger is queued for charging and carried, since a stalled display is
   alive and still holds the scenes.
6. **The death queue needs no bound the model can see, and a bound of one loses a
   death.** Two deaths queued at once is reachable (`card(dom(dqown)) = 2`; the
   replicator mid-push, the dial redialled twice by other parties). A control that keeps
   one queued death and evicts the older violates A1. The code's earlier
   `deque(maxlen=64)` was the same defect at a larger scale (`review-r7-invariants.md`
   F-4); the queue is now unbounded (`death_queue.py`) and warns past 64.

## Known bounds (stated, not defects)

- **B1, a late reveal.** A scene the user brings into view after its swap (background
  tab, restored minimised frame) was acked at the swap. A crash on its first paint is not
  attributed. The model cannot show it as a trace, because its poison scene never
  completes a swap.
- **B2, over-charge.** The suspects are a superset: scenes in transit, scenes held and not
  yet swapped, and the carried set. In batching mode an innocent scene written alongside
  the culprit takes the same strike. In isolation a ledger is at most one scene written
  after the first strike, plus whatever batching left unacked, plus the carried set. A
  carried scene that the display no longer holds (the display was replaced) can be
  charged; the bound is the Hub-ended and unresponsive ledgers since the last applied ack.
- **B3, the stall**: item 5 above.
- **B4, a crash with no dial live** is not observed. The carried set persists and is
  charged at the next display-ended death unless an ack read clears it first, in which
  case the old crash is lost (the display is a new one). A1 counts only crashes observed
  on a live dial.
- **B6, the poison scene** kills the display at install or in the first frame after it,
  and never completes a swap. Other scenes are acked at the swap after install; the
  display may also end spontaneously.
- **B7, several Hubs on one display** (DES-089). A death caused by Hub B's scene ends Hub
  A's dial with cause display, and Hub A charges its own ledger and carried set though none
  of its scenes caused it. Under T11 Hub A's suspects are everything it sent that was
  received since the last swap; in a crash loop driven by Hub B, Hub A (isolating once
  struck) has its one scene in flight struck on every turn, at the rate of Hub B's culprit.
  The bound is Hub A's ledger and carried set per death of the shared display. The model has
  one Hub, and A2 is worded accordingly. DES-102 should state the bound.

## Obligations on the code

- **O1** The replicator is the only charger, and it charges the whole queue before it
  filters or sends in a push, and on its idle tick (a mid-push redial may leave a death
  queued until the next push; the model includes that). The queue is a capability: the
  registry hands it out once, to the charger, so no other part of the Hub can take a
  death out of it. A death whose charge raises goes back at the head and is charged
  again before any later one.
- **O2** The settlement (T14): a dial is settled by the holder of its reader slot, and a
  display death becomes a Hub end only through the bound or through P9, as DES-102 states.
  The proof is `dial_settlement.tex` (S1-S5); this is what the code owes it. A display or
  unresponsive end records its cause, first wins; a Hub end records nothing, it requests a
  settle and refuses writes (`DialEnd`, `ReplySink`). The holder's `Settler` (`settler.py`,
  made only by `ReaderSlot`) drains what the socket holds to the point of blocking, routes
  every complete frame, fixes the cause by the first-wins record (end of file means the
  display's, a pending Hub request the Hub's, otherwise the recorded cause), drains once
  more if a display or unresponsive end was recorded after its drain began, and only then
  takes the ledger (`DisplayConnection._capture`, before `shut()` discards the queue). On
  `AF_UNIX` an ack the display sent is already in the Hub's receive queue; over a
  cross-host reset it may not be. Whoever ends a dial without holding the slot asks
  (`ReaderSlot.ask_settle`): a free slot is taken and the dial settled on the spot; a held
  slot is refused and leaves a debt, in the critical section that saw it held, and every
  release honours the debt in the critical section that frees the slot. A refused asker
  waits for the holder up to `SETTLE_BOUND`; past it the asker captures through the
  `BoundedAsk` the refusal handed it. A holder whose own drain cannot be made (a writer
  held the socket past the ceiling, `DrainIncompleteError`) leaves its capture to the same
  bound. Seven residuals are named and accepted: P9 (a display that dies after the
  settler's last observation is captured as a Hub end) and the six exceptions to A1 and A2
  of `dial_settlement.tex`: s5blk (a display dead while a Hub request is pending,
  captured by the bound as a Hub end: its suspects are carried, a later ack clears them,
  and that poison death goes uncharged), s2blk (a display or unresponsive end captured by
  the bound is undrained, so it may charge scenes whose acks were never read, in two
  causes, display and unresponsive), s2dec (an undecodable stream is captured without a
  drain, by `Settler.end_stream`), s2lat (a display or unresponsive end captured,
  undrained, by the settler's own late capture because a writer held the socket past the
  ceiling while an ack or the end of file was readable: an over-charge, bounded by the
  ceiling plus the bound) and a1late (a scene written while a capture lands between
  `sendall` returning and `owe_ack`: an under-charge of one scene per dial, late by one
  dial, since the write raises and the replicator's recovery re-marks the scene). A
  drain that applies an ack clears the carried set as any applied ack does.
- **O3** The carried set is cleared by an applied ack and by a display-ended capture, and
  grows by a Hub-ended ledger; an unresponsive capture replaces it with the suspects it
  queued. A display-ended death with an empty ledger and a non-empty carried set charges
  the carried set; with both empty, nothing.
- **O4** The death queue never drops a death.
- **O5** The display sends held acks only after a completed swap, in receipt order,
  including hidden scenes; an ack held for a dead dial is dropped.
- **O6** Isolation releases the next scene on the applied ack for the previous one, never on
  a pong; when its wait is exhausted it does not send. (`batch_sender.py`, `_isolating`
  waits on `DisplayRequests.await_acks`; it used to release on a pong.)
- **O7** No earlier dial's scene is installed after a later dial's. This is a property of
  the code: a scene from a socket that has not identified is refused with no ack
  (`render_loop.py`, `hub_reconciliation.py`); the new dial's `ConnectMessage` precedes its
  scenes on the same stream, and the display, handling it, closes the predecessor that
  declared the same `HubId` (DES-068 preemption, `hub_reconciliation.py`,
  `socket_server.py`), discarding every byte it has not read; a predecessor already removed
  reached end of file, so all its bytes were read first. The preemption is keyed on `HubId`
  on both the same-host and the cross-host leg (W11). The residue is narrow: a predecessor
  that has not yet identified, and a `HubId` that changes within one Hub process. This is
  what makes the carried set's clear sound.

## Bounds, and why they reach the defects

`maxDial = 2`, `maxScene = 2`, `thr = 2`, `poison = 1`, discoverers `drepl | dother`.
Every control reaches its violation inside these bounds, so the bounds reach the defects.
Two dials: a death must be discovered after a redial, and a carried scene charged on the
next dial. Two scenes: one innocent scene to be wrongly charged. Threshold two: one
death is not yet a quarantine, so the loop has a length. The design was also run at three
dials and at three scenes (above) to show the result does not depend on the smallest
carrier. The model is flat, with bounded integers and no given sets, so no `-card`.

## Results

`fuzz` clean on each file separately. `probcli` at
`/home/jfreeman/Applications/ProB/probcli`, one run at a time on scratch copies under
`.tmp/ca-t12/` (identical to the committed files), with about 14 GB available throughout.

```text
fixed, maxDial 2, maxScene 2:  -model_check -coverage -p MAX_OPERATIONS 200
   -> 30,883 states, 81,242 transitions, no counter example, ALL states visited,
      deadlocked:0, UNCOVERED_OPERATIONS (0)
fixed:  -model_check -nodead -bf -goal "<A1 or A2 or A3 or A4>"
   -> no counter example, ALL 30,883 states visited   (each goal alone: the same)
fixed, maxDial 3:  same goal (quantifiers over 0..3)
   -> 2,143,829 states, 5,833,534 transitions, no counter example, ALL states visited
fixed, maxScene 3: same goal
   -> 718,209 states, 2,027,022 transitions, no counter example, ALL states visited
inflight_ack_drain, maxDial 2, maxScene 2:  the goal
   -> 30,883 states, no counter example
```

Non-vacuity (goal **found** on the fixed design, `-model_check -nodead -bf -goal`):

| Goal | Found, states |
|---|---|
| a carried scene is charged (`carriedOn /= {}`) | 2,177 |
| two deaths queued at once (`card(dom(dqown)) = 2`) | 482 |
| the poison scene quarantined (`strikes(1) = 2`) | 4,195 |
| an innocent scene quarantined (`strikes(2) = 2`) | 4,842 |
| an innocent scene charged for a poison death | 398 |
| the culprit charged through a Hub-ended dial's carried set | 3,770 |
| the culprit charged through an unresponsive dial's carried set | 3,863 |
| an unresponsive dial settled, its suspects queued | 50 |
| an ack taken off the socket and not applied when the display dies (`rbuf /= {}`) | 238 |
| a settled Hub-ended dial with a non-empty ledger | 48 |
| an idle stop (display-ended, nothing written, nothing carried) | 13 |
| the display holds the poison scene with no dial live | 100 |
| isolation: a dial live after a charge, one scene written and its ack applied | 14,308 |

Controls (`-model_check -nodead -bf -goal`, one goal at a time):

| Control | A1 | A1w | A2 | A3 | A4 | Shortest trace |
|---|---|---|---|---|---|---|
| `ack_on_receipt_buggy` | **found** (431) | **found** (2,657) | not found | not found | not found | A1: `PushStart; Redial; Send(1); Install(1); Recv(1); Deliver(1); CrashFrame; DiscoverQuiet`: acked, then dies painting, never charged (gvr's trace). A1w: `PushStart; Redial; Send(1); Send(2); Install(1); PushEnd; Recv(1); CrashFrame; Deliver(1); DiscoverCharge; Charge`: the innocent later scene is charged, the culprit is not |
| `no_carry_buggy` | **found** (918) | **found** (6,430) | not found | not found | not found | Hub door, A1: `PushStart; Redial; Send(1); Install(1); HubEnd; DiscoverHub; Redial; CrashFrame; DiscoverQuiet`. A1w: `...; Redial; Send(2); CrashFrame; PushEnd; DiscoverCharge; Charge`. Probe door (A1w, 6,546): `PushStart; Redial; Send(1); Install(1); Unresponsive; DiscoverUnrCharge; Redial; Send(2); CrashFrame; PushEnd; DiscoverCharge; Charge` |
| `inflight_ack_buggy` | not found | not found | **found** (2,347) | not found | not found | `PushStart; Redial; Send(2); Install(2); Swap; DisplayEnd; Recv(2); DiscoverCharge(dother); PushEnd; Charge`: the reader holds the ack, a non-reader captures, the socket is empty (jra's trace). With no guard at all: 9 steps, 1,161 states |
| `inflight_ack_drain` (variant) | not found | not found | not found | not found | not found | holds: 30,883 states |

The `no_carry` control's probe door is reached with the goal conjoined with `ended(1) = eunr`.

Extra controls, regenerated in scratch and not committed (they test the checks, not the
design): a control in which an applied ack does not clear the carried set violates the
carried-set clause of A2 (18,262 states), so that clause is not vacuous; a control that
keeps one queued death and evicts the older violates A1 (1,095 states). A control in
which only the unresponsive discovery carries nothing violates A1 and A1w (945 and 6,572
states) and leaves the Hub-end door closed; it is committed as
`crash_attribution_unresponsive_no_carry_buggy.tex`.

The four T10 controls are committed beside the specification, regenerated against it:
each models the hold, the swap, the carried set and the queue, and each reproduces its
defect:

| T10 control | Violated | States | Trace |
|---|---|---|---|
| `redial_only` | A1 | 50 | `PushStart; Redial; Send(1); CrashInstall; DiscoverDrop(dother)`: a non-replicator's discovery discards the evidence (silent F1) |
| `idle_stop` (a substitution, not a one-line mutation: it deletes `DiscoverCharge`, replaces `DiscoverQuiet` with `DiscoverBlame` and adds `SendBlamed` and `blame`, encoding the T10-era "charge the next scene sent") | A2 (and A1, A1w) | 118 | `Redial; DisplayEnd; DiscoverBlame(dother); Redial; PushStart; SendBlamed(1)`: a scene never written to the dead dial is charged |
| `hub_end_charged` | A3 | 255 | `PushStart; Redial; Send(1); HubEnd; PushEnd; DiscoverCharge(dother); Charge`: a dial the Hub retired is charged (code F1's shape) |
| `double_charge` | A4 | 1,018 | `PushStart; Redial; Send(1); PushEnd; DisplayEnd; DiscoverCharge(drepl); Charge; DiscoverCharge(dother); Charge`: two discoverers of one death, two strikes |

The files are `crash_attribution_{redial_only,idle_stop,hub_end_charged,double_charge}_buggy.tex`
and `crash_attribution_unresponsive_no_carry_buggy.tex` in this directory.

What T10 does not cover, by construction: a death that the Hub retires first (cause
`hub`) is never charged as the display's own, even when the display had in fact died;
under T12 its ledger is carried and charged at the next display-ended death. A dial the
keepalive or the isolation probe retires (cause `unresponsive`) is charged at once, as
DES-102 ratifies, and also carried (T13).

## Partitions and the tests that cover them

Each row is a partition of the model's behaviour. A test must drive the real components,
not a fake sender that raises inside the send, and not a display that never acks a
poisoned scene or acks it on receipt. A test that stubs the mechanism is a gap.

| Partition | Model operations | Tests |
|---|---|---|
| P1 Display death discovered by the replicator's own send | `DisplayEnd; DiscoverCharge(drepl); Charge` | `tests/domain/test_retire_cause.py::TestADeathDiscoveredByAnyParty::test_p1_the_replicators_own_send_leaves_the_death_of_the_unacked_scene`, `::test_p1_the_ledger_names_the_written_scene_not_the_one_that_failed`; `tests/integration/test_crash_quarantine.py::test_a_scene_that_crashes_the_display_is_quarantined_at_the_threshold` (the acking `Responder(at_swap=True)`, P24); the at-swap rig for the same discovery: `tests/domain/test_ack_attribution.py::TestAScenePaintedToDeathIsCharged::test_p13_a_crash_before_the_swap_leaves_every_installed_scene_unacked` |
| P2 Death discovered by a non-replicator redial between pushes | `DisplayEnd; DiscoverCharge(dother); Redial` | `tests/domain/test_retire_cause.py::TestADeathDiscoveredByAnyParty::test_p2_a_poison_scene_is_quarantined_when_another_party_wins_every_redial` |
| P3 Death discovered by the reader or keepalive, no redial yet | `DisplayEnd; DiscoverCharge(dother)` | `::test_p3_a_death_is_charged_at_discovery_and_the_redial_does_not_recharge_it` |
| P4 Charge once per dial, however many parties discover | `DiscoverCharge`, a settled dial, `Charge` | `::test_p4_two_discoverers_of_one_dial_charge_one_strike_and_a_new_dial_another`; `tests/domain/test_death_charger.py::TestCharging::test_a_death_is_charged_once_however_often_the_charger_looks` |
| P4b The charge is first in the push, before the filter and any send | `PushStart` enabled only with the queue empty | `::test_the_next_push_charges_a_death_before_it_sends_anything`. The "only charger" half (O1): `tests/domain/test_single_writer.py::TestTheReplicatorIsTheOnlyCharger` (`DeathCharger` is built once, inside `BatchSender`, which only the replicator builds) and `::TestTheDeathQueueIsTheChargersAlone` (the queue is asked for only where it is handed on, once per hop, and `tests/domain/test_link_generations.py::TestTheDeathQueueIsHandedOutOnce` refuses a second asker) |
| P5 Hub-ended dial, ledger non-empty, writer woken | `HubEnd; DiscoverHub` | `::TestADeathTheHubEndedChargesNothing::test_p5_a_write_woken_by_the_hubs_retire_charges_nothing`; `::test_a_hub_end_queues_no_death`; `::TestADialTheHubEnded` |
| P5b Hub-ended dial, **inline read** woken by a Hub retire on another thread | `HubEnd; DiscoverHub` | `tests/domain/test_retire_cause.py::TestADeathTheHubEndedChargesNothing::test_p5_an_unlistened_inline_read_woken_by_the_hubs_retire_charges_nothing` (`_linked(display, listening=False)`, a scene owed, asserts `HubRetiredError` and no death); the listener-waiting form is `::test_p5_a_ping_waiting_on_the_reader_woken_by_the_hubs_retire_charges_nothing` |
| P6 Display-ended dial, empty ledger and empty carried set (idle stop) | `DisplayEnd; DiscoverQuiet` | `::TestADeathThatOwedNothing::test_p6_a_stop_while_idle_charges_no_later_scene` |
| P7 An acked scene is not a suspect | `Swap; Recv; Deliver; DisplayEnd` | `::test_p7_an_acked_scene_is_not_a_suspect`; at the swap, with the acking display: `tests/domain/test_ack_attribution.py::TestAScenePaintedToDeathIsCharged::test_p13_a_crash_after_the_swap_does_not_charge_the_acked_scene` (P13) |
| P8 A scene written only to a later dial is not charged for an earlier | `Send` on dial 1, redial, `Send` on dial 2 | `::test_p8_a_scene_written_only_to_a_later_dial_is_not_charged_for_an_earlier`; `tests/domain/test_death_charger.py::TestCharging::test_a_scene_outside_the_ledger_is_never_charged`, `::test_every_scene_in_a_ledger_takes_a_strike_and_none_outside_it` |
| P9 Isolation narrows the suspects | `Send` guard: ledger empty once a strike exists | `::TestIsolationNarrowsTheSuspects::test_p9_a_death_in_isolation_charges_the_one_scene_in_flight`; `::TestAnUnackedProbeIsTheDisplaysEnd::test_an_unacked_isolation_probe_leaves_the_death_of_the_scene_sent`; with the acking display, the probe waits on the ack (P21): `tests/domain/test_ack_attribution.py::TestAnIsolationProbeWaitsOnTheAck::test_p21_the_next_scene_is_not_sent_until_the_previous_is_acked` |
| P10 Quarantine boundary | `strikes = thr` leaves `dirty`; `Send` guard | `::test_p10_a_quarantined_scene_is_never_sent_again` |
| P11 Deadlock-freedom, the last dial | `Halt` | `::TestTheLastDial::test_p11_a_display_that_stays_down_is_charged_once_not_every_cycle` |
| P12 An ack is held until the swap | `Install; Swap; Recv; Deliver` | Display: `tests/display/test_held_acks.py::TestAnAckIsHeldUntilTheSwap` (`test_installing_a_scene_sends_no_ack`, `test_the_swap_sends_the_ack`, `test_an_ack_is_sent_once_whatever_the_number_of_swaps`); Hub: the acking `Responder(at_swap=True)` of `tests/domain/display_double.py` drives every case of `tests/domain/test_ack_attribution.py` |
| P13 A crash before the swap (install, or first frame) leaves the scene unacked; a crash after the swap does not charge it | `CrashInstall`, `CrashFrame`; `Swap; DisplayEnd` | `tests/domain/test_ack_attribution.py::TestAScenePaintedToDeathIsCharged::test_p13_a_crash_before_the_swap_leaves_every_installed_scene_unacked` and `::test_p13_a_crash_after_the_swap_does_not_charge_the_acked_scene` |
| P14 Held acks flushed in receipt order at one swap | `Swap` | `tests/display/test_held_acks.py::TestHeldAcksGoOutInReceiptOrder` (`test_one_swap_flushes_every_held_ack_in_the_order_received`, `test_a_scene_received_after_a_swap_waits_for_the_next`); a client gone before the swap: `::TestAClientThatLeftBeforeTheSwap` |
| P15 A scene in a hidden tab or minimised frame is acked at the swap | `Install; Swap` (visibility is not modelled: every held scene is acked) | `tests/display/test_held_acks.py::TestAnAckDoesNotDependOnVisibility` (a docked frame, a closed frame) |
| P16 Carry across a Hub-ended dial: the poison scene held on a retired dial crashes the display on the next | `Send; Install; HubEnd; DiscoverHub; Redial; CrashFrame; DiscoverCharge; Charge` | `tests/domain/test_ack_attribution.py::TestSuspectsOutliveAHubEndedDial::test_p16_the_poison_scene_held_on_a_retired_dial_is_charged_on_the_next` (the counterexample to T11 alone: the culprit is in the death's suspects); the arithmetic in isolation: `tests/domain/test_suspect_book.py` |
| P17 The carried set is cleared by an applied ack on a later dial, and by a display-ended capture | `Deliver`, `DiscoverCharge` | `tests/domain/test_ack_attribution.py::TestSuspectsOutliveAHubEndedDial::test_p17_an_ack_read_on_a_later_dial_clears_the_carried_set`; the capture's clear: `tests/domain/test_suspect_book.py::TestADialTheDisplayEnded::test_it_charges_what_it_owed_and_the_book_is_then_empty` |
| P18 A display-ended capture with an empty ledger and a non-empty carried set charges the carried set | `DiscoverCharge` with `dqown = {}` | `tests/domain/test_ack_attribution.py::TestSuspectsOutliveAHubEndedDial::test_p18_a_death_with_an_empty_ledger_charges_the_carried_set` (a Hub drop, and the Hub's deliberate close) |
| P19 An ack in flight at retire: the drain | `Swap; DisplayEnd; Recv; Deliver; DiscoverCharge` | `tests/domain/test_ack_attribution.py::TestTheAckInFlightAtRetire`: `test_an_ack_in_the_socket_when_a_non_reader_ends_the_dial_is_not_charged` (the discoverer, with no reader, takes the slot and drains), `test_an_ack_the_reader_has_read_and_not_applied_is_not_charged` (the reader holds the ack off the socket; a non-reader ends the dial; the ledger is taken only after it is applied), `test_an_ack_still_in_the_socket_when_the_reader_settles_is_not_charged`, `test_a_hub_retire_after_a_display_end_leaves_the_ledger_to_the_reader`, `test_an_end_recorded_as_an_inline_read_finishes_is_settled_before_it_lets_go`; the drain itself: `tests/domain/test_dial_drain.py`; the three steps of the end (a recorded or requested end, the decision, the capture): `tests/domain/test_reply_sink.py` and `tests/domain/test_dial_settlement.py` (P8, P9, P18) |
| P20 The swap stall | `Install; Install; DisplayEnd` with no `Swap` | `tests/domain/test_ack_attribution.py::TestAStalledDisplay::test_p20_a_death_charges_every_scene_since_the_last_swap_and_none_outside`; the isolation probe's timeout retires the dial as unresponsive, queued and carried: `::TestAnIsolationProbeWaitsOnTheAck::test_p21_when_no_ack_comes_the_next_scene_is_not_sent_and_the_dial_is_given_up` |
| P21 The isolation probe clears on the applied ack | `Send` guard | `tests/domain/test_ack_attribution.py::TestAnIsolationProbeWaitsOnTheAck::test_p21_the_next_scene_is_not_sent_until_the_previous_is_acked` (a pong is answered at once and the next scene still waits) and `::test_p21_when_no_ack_comes_the_next_scene_is_not_sent_and_the_dial_is_given_up`; at the port: `tests/domain/test_link_generations.py::TestBusyIsNotDead` (`test_a_pong_does_not_answer_an_ack_wait`, `test_the_ack_that_empties_the_ledger_answers_the_wait`, `test_an_ack_wait_the_display_never_answers_is_false_and_keeps_the_dial`) |
| P22 The death queue drops nothing while the replicator is away | `Charge` with `card(dom(dqown)) = 2` | `tests/domain/test_death_queue.py::TestAQueueThatGrows::test_past_the_warning_mark_every_death_is_kept_and_it_says_so` and `tests/domain/test_suspect_book.py::TestTheDeathsWaitingToBeCharged::test_past_the_warning_mark_every_death_is_kept_and_the_book_says_so` (70 deaths, all kept, one warning); through the connection: `tests/domain/test_display_connection.py::TestThePendingDeathsAreNeverDropped` |
| P23 A crash with no dial live: the carried set outlives it | `HubEnd; DisplayEndDown; Redial` | `tests/domain/test_ack_attribution.py::TestSuspectsOutliveAHubEndedDial::test_p23_the_carried_set_outlives_a_crash_no_dial_saw` |
| P24 The integration display behaves like the real one | all | `tests/integration/test_crash_quarantine.py::test_a_scene_that_crashes_the_display_is_quarantined_at_the_threshold` runs the real replicator and keepalive against `Responder(at_swap=True)`, which holds every ack to a swap and dies on the swap that carries the poison scene; and `tests/domain/test_ack_attribution.py::TestAScenePaintedToDeathIsCharged::test_p24_the_poison_scene_reaches_quarantine_within_the_threshold` with another party winning every redial |
| P25 A probe retire of a live display that holds the culprit, then a crash on the next dial | `Send; Install; Unresponsive; DiscoverUnrCharge; Redial; CrashFrame; DiscoverCharge; Charge` | `tests/domain/test_ack_attribution.py::TestAnUnresponsiveDialIsCarriedAndCharged::test_p25_a_scene_held_on_an_unresponsive_dial_is_charged_on_the_next_crash` (the culprit is charged on the probe dial and again through the carried set); `::test_a_request_on_an_unresponsive_dial_is_told_the_display_stopped_answering`; `::test_an_unresponsive_death_says_the_display_stopped_answering` |
| P26 O7: the predecessor is preempted before the new dial's first scene | `Install` only on the live dial | `tests/display/test_install_order.py::TestAPredecessorIsClosedBeforeTheNewDialsFirstScene` (nothing from the predecessor is installed after the new dial identifies) and `::TestAnUnidentifiedSocketsSceneIsRefusedAndNeverAcked`; the preemption policy itself: `tests/display/test_render_loop.py::TestHandleConnectDispatch`, `tests/display/test_hub_reconciliation.py::TestHandleConnect` |
| P27 A Hub end is a request, not a recorded cause; the settle decides it (a display end the reader sees is the display's, else a request is the Hub's); a writer's record is one step with its check | `HubEnd` (a request), `DisplayEnd`, `DiscoverHub`, `WRec` interleaved with the reader's `Recv`, `Deliver`, decision, capture | `tests/domain/test_dial_settlement.py`: P8 and P9 (a request, then the decision by what the reader saw), P18 (a write failing after a request records nothing, live and dead display), the writer's atomic record (`test_a1_a_hub_request_landing_before_the_writers_record_wins`); `tests/domain/test_hub_end_atomic.py` (a display end landing in a Hub retire, with a reader busy and with none; a stop or close racing an end somebody recorded); the inline reader that loses the end: `tests/domain/test_retire_cause.py::TestAHubRetireThatLandsBetweenTheCheckAndTheRetire`; every capture is a door of the slot, pinned by `tests/domain/test_settlement_door.py` |
| P28 A skewed ack leaves the ledger whole; a drain that cannot route a reply stops | `Deliver` with an ack that is not the head | `tests/domain/test_dial_drain.py::TestASkewedAckLeavesTheLedgerWhole`; the drain says when it is cut short: `::TestACutShortDrainSaysSo` |
| P29 The acks held for a swap share one bounded post-swap deadline | `Swap` | `tests/display/test_held_acks.py::TestTheHeldAcksShareOnePostSwapBudget` |
| B1 A late reveal is not attributed | none (outside the model) | documented by `tests/display/test_held_acks.py::TestAnAckDoesNotDependOnVisibility` (a scene in a docked or closed frame is acked at the swap, before it is first painted) and `tests/domain/test_ack_attribution.py::TestAScenePaintedToDeathIsCharged::test_p13_a_crash_after_the_swap_does_not_charge_the_acked_scene` (an acked scene is not charged for a later crash) |
| B7 Another Hub's crash charges this Hub's ledger and carried set | none (one Hub modelled) | `tests/domain/test_ack_attribution.py::TestAnotherHubsCrash::test_b7_each_hub_charges_its_own_ledger_and_no_more` (Hub A's death is exactly its own ledger, struck for a crash Hub B's scene caused) |

Re-run `fuzz`, the model-check and the controls whenever the attribution path changes who
charges, from what evidence, when, or what an ack means.
