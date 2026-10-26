# Crash attribution: model results and coverage audit

Spec: [crash_attribution.tex](./crash_attribution.tex). Fidelity controls:
[ack_on_receipt](./crash_attribution_ack_on_receipt_buggy.tex) (today's code),
[no_carry](./crash_attribution_no_carry_buggy.tex) (T11 without T12, through both the
Hub's retire and the probe's),
[inflight_ack](./crash_attribution_inflight_ack_buggy.tex) (capture without the split-read
guard). Design variant: [inflight_ack_drain](./crash_attribution_inflight_ack_drain.tex).
Governs `src/punt_lux/domain/hub/{batch_sender,recovery,display_connection,
dial_generation,reply_sink,liveness_probe,replicator,death_charger}.py` and the display's
ack in `src/punt_lux/display/render_loop.py`.

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
| A1 | Every poison death observed on a live dial is, once settled and no longer queued, charged to the poison scene (own ledger or carried set), whichever party discovered it, across Hub-ended and unresponsive dials and while the replicator is away. A1w: the wrong scene is charged in its place | `close_if_current` queues the dead dial's suspects once, at discovery, in the hold that retires it; `take_deaths` hands the queue over once; the one replicator charges it first at its next push or idle tick, before the quarantine filter; the carried set rides in the death |
| A2 | No scene is charged for a death of a display this Hub was attached to unless it was in that death. Per write, not per scene id: an acked earlier write of a scene does not clear a later, unacked one. Own ledger: a scene written to the dial whose ack the display did not send (an ack in flight, or taken off the socket and not applied, counts as sent). Carried set: a scene written to an earlier Hub-ended or unresponsive dial, with no ack applied and no display-ended death since | ledger = written minus acked, captured by the reader after the drain; carried set = Hub-ended and unresponsive ledgers since the last applied ack |
| A3 | A Hub-ended dial charges no scene (its ledger is carried, which is not a charge). An unresponsive dial is the display's end for DES-102 and does charge | queue only when `cause` is `display` or `unresponsive`; a Hub-ended retire appends to the carried set |
| A4 | Each dial's death is charged at most once | `close_if_current` succeeds once per generation; the queue is drained under the state lock |

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
   one queued death and evicts the older violates A1. The code's `deque(maxlen=64)` is
   the same defect at a larger scale (`review-r7-invariants.md` F-4); the queue must be
   unbounded or coalesce by summing strikes.

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
  queued until the next push; the model includes that).
- **O2** The drain (T14): a display-ended or unresponsive capture is made by the dial's own
  reader, or waits for it. Before it takes the ledger the reader (1) reads what the socket
  already holds, non-blocking, until `EAGAIN` or end of file (on `AF_UNIX` an ack the
  display sent is already in the Hub's receive queue), (2) delivers every complete frame it
  holds, and only then takes the ledger, before `shut()` discards the queue. A non-reader
  discoverer signals; it does not capture. A drain that applies an ack clears the carried
  set as any applied ack does.
- **O3** The carried set is cleared by an applied ack and by a display-ended capture, and
  grows by a Hub-ended ledger; an unresponsive capture replaces it with the suspects it
  queued. A display-ended death with an empty ledger and a non-empty carried set charges
  the carried set; with both empty, nothing.
- **O4** The death queue never drops a death.
- **O5** The display sends held acks only after a completed swap, in receipt order,
  including hidden scenes; an ack held for a dead dial is dropped.
- **O6** Isolation releases the next scene on the applied ack for the previous one, never on
  a pong; when its wait is exhausted it does not send. The code today releases on a pong
  (`batch_sender.py`, `_isolating`): this is a change the implementation must make, not a
  property it has.
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
keeps one queued death and evicts the older violates A1 (1,095 states); a control in which
only the unresponsive discovery carries nothing violates A1 and A1w (945 and 6,572
states) and leaves the Hub-end door closed.

The T10 controls, regenerated against this specification in scratch (their committed
files still model the T10 state: no hold, swap, carry or queue), each still reproduce
their defect:

| T10 control | Violated | States | Trace |
|---|---|---|---|
| `redial_only` | A1 | 50 | `PushStart; Redial; Send(1); CrashInstall; DiscoverDrop(dother)`: a non-replicator's discovery discards the evidence (silent F1) |
| `idle_stop` (a substitution, not a one-line mutation: it deletes `DiscoverCharge`, replaces `DiscoverQuiet` with `DiscoverBlame` and adds `SendBlamed` and `blame`, encoding the T10-era "charge the next scene sent") | A2 (and A1, A1w) | 118 | `Redial; DisplayEnd; DiscoverBlame(dother); Redial; PushStart; SendBlamed(1)`: a scene never written to the dead dial is charged |
| `hub_end_charged` | A3 | 255 | `PushStart; Redial; Send(1); HubEnd; PushEnd; DiscoverCharge(dother); Charge`: a dial the Hub retired is charged (code F1's shape) |
| `double_charge` | A4 | 1,018 | `PushStart; Redial; Send(1); PushEnd; DisplayEnd; DiscoverCharge(drepl); Charge; DiscoverCharge(dother); Charge`: two discoverers of one death, two strikes |

The regenerated files are at `.tmp/missions/results-model-t12/controls/`, with the scratch
unresponsive-door control. Replacing the committed T10 files with them is a separate pass.

What T10 does not cover, by construction: a death that the Hub retires first (cause
`hub`) is never charged as the display's own, even when the display had in fact died;
under T12 its ledger is carried and charged at the next display-ended death. A dial the
keepalive or the isolation probe retires (cause `unresponsive`) is charged at once, as
DES-102 ratifies, and also carried (T13).

## Partitions and the tests that cover them

Each row is a partition of the model's behaviour. A test must drive the real components,
not a fake sender that raises inside the send, and not a display that never acks a
poisoned scene or acks it on receipt. A test that stubs the mechanism is a gap.
"To be written (T11/T14)" marks a partition no test covers today.

| Partition | Model operations | Tests |
|---|---|---|
| P1 Display death discovered by the replicator's own send | `DisplayEnd; DiscoverCharge(drepl); Charge` | `tests/domain/test_retire_cause.py::TestADeathDiscoveredByAnyParty::test_p1_the_replicators_own_send_leaves_the_death_of_the_unacked_scene`, `::test_p1_the_ledger_names_the_written_scene_not_the_one_that_failed`; `tests/integration/test_crash_quarantine.py::test_a_scene_that_crashes_the_display_is_quarantined_at_the_threshold` (its scripted display never acks the poison scene: rerun against the acking display, P24) |
| P2 Death discovered by a non-replicator redial between pushes | `DisplayEnd; DiscoverCharge(dother); Redial` | `test_retire_cause.py::TestADeathDiscoveredByAnyParty::test_p2_a_poison_scene_is_quarantined_when_another_party_wins_every_redial` |
| P3 Death discovered by the reader or keepalive, no redial yet | `DisplayEnd; DiscoverCharge(dother)` | `::test_p3_a_death_is_charged_at_discovery_and_the_redial_does_not_recharge_it` |
| P4 Charge once per dial, however many parties discover | `DiscoverCharge`, a settled dial, `Charge` | `::test_p4_two_discoverers_of_one_dial_charge_one_strike_and_a_new_dial_another`; `tests/domain/test_death_charger.py::TestCharging::test_a_death_is_charged_once_however_often_the_charger_looks` |
| P4b The charge is first in the push, before the filter and any send | `PushStart` enabled only with the queue empty | `::test_the_next_push_charges_a_death_before_it_sends_anything`. The "only charger" half (O1): to be written (T11/T14) |
| P5 Hub-ended dial, ledger non-empty, writer woken | `HubEnd; DiscoverHub` | `::TestADeathTheHubEndedChargesNothing::test_p5_a_write_woken_by_the_hubs_retire_charges_nothing`; `::test_only_a_display_end_queues_a_death`; `::TestADialTheHubEnded` |
| P5b Hub-ended dial, **inline read** woken by a Hub retire on another thread | `HubEnd; DiscoverHub` | MISSING: `::test_p5_an_inline_read_woken_by_the_hubs_retire_charges_nothing` runs on `_rig`, whose dial has a listener, so it never takes the inline path. To be written (T11/T14): `_linked(display, listening=False)`, a dial with an owed scene, assert `HubRetiredError` and `take_deaths() == ()` |
| P6 Display-ended dial, empty ledger and empty carried set (idle stop) | `DisplayEnd; DiscoverQuiet` | `::TestADeathThatOwedNothing::test_p6_a_stop_while_idle_charges_no_later_scene` |
| P7 An acked scene is not a suspect | `Swap; Recv; Deliver; DisplayEnd` | `::test_p7_an_acked_scene_is_not_a_suspect` (acks at receipt in its rig: to be rerun against T11 acks, P12) |
| P8 A scene written only to a later dial is not charged for an earlier | `Send` on dial 1, redial, `Send` on dial 2 | `::test_p8_a_scene_written_only_to_a_later_dial_is_not_charged_for_an_earlier`; `tests/domain/test_death_charger.py::TestCharging::test_a_scene_outside_the_ledger_is_never_charged`, `::test_every_scene_in_a_ledger_takes_a_strike_and_none_outside_it` |
| P9 Isolation narrows the suspects | `Send` guard: ledger empty once a strike exists | `::TestIsolationNarrowsTheSuspects::test_p9_a_death_in_isolation_charges_the_one_scene_in_flight`; `::TestAnUnansweredProbeIsTheDisplaysEnd::test_an_unanswered_isolation_probe_leaves_the_death_of_the_scene_sent` (a pong, not the ack: to be rerun for P21) |
| P10 Quarantine boundary | `strikes = thr` leaves `dirty`; `Send` guard | `::test_p10_a_quarantined_scene_is_never_sent_again` |
| P11 Deadlock-freedom, the last dial | `Halt` | `::TestTheLastDial::test_p11_a_display_that_stays_down_is_charged_once_not_every_cycle` |
| P12 An ack is held until the swap | `Install; Swap; Recv; Deliver` | to be written (T11/T14): a display-side test that `_handle_scene` sends no ack, and `_on_after_swap` sends it; and a Hub-side rig whose acking `Responder` acks only after the swap |
| P13 A crash before the swap (install, or first frame) leaves the scene unacked; a crash after the swap does not charge it | `CrashInstall`, `CrashFrame`; `Swap; DisplayEnd` | to be written (T11/T14): a pre-ack crash case (the `Responder` hangs up on the poison scene before any ack) and a post-ack crash case (acked scene survives, a later unacked scene is charged) |
| P14 Held acks flushed in receipt order at one swap | `Swap` | to be written (T11/T14) |
| P15 A scene in a hidden tab or minimised frame is acked at the swap | `Install; Swap` (visibility is not modelled: every held scene is acked) | to be written (T11/T14) |
| P16 Carry across a Hub-ended dial: the poison scene held on a retired dial crashes the display on the next | `Send; Install; HubEnd; DiscoverHub; Redial; CrashFrame; DiscoverCharge; Charge` | to be written (T11/T14): the counterexample to T11 alone; assert the culprit is charged |
| P17 The carried set is cleared by an applied ack on a later dial, and by a display-ended capture | `Deliver`, `DiscoverCharge` | to be written (T11/T14) |
| P18 A display-ended capture with an empty ledger and a non-empty carried set charges the carried set | `DiscoverCharge` with `dqown = {}` | to be written (T11/T14) |
| P19 An ack in flight at retire: the drain | `Swap; DisplayEnd; Recv; Deliver; DiscoverCharge` | to be written (T11/T14): two cases. The ack is in the socket buffer when a non-reader retires the dial; and the reader holds the ack, taken off the socket and not delivered, when it does (the race `inflight_ack` shows). Assert the acked scene is not charged (O2) |
| P20 The swap stall | `Install; Install; DisplayEnd` with no `Swap` | to be written (T11/T14): held acks pile up, a death charges every scene since the last swap, none outside; and in isolation the probe's timeout retires the dial as unresponsive, queued and carried |
| P21 The isolation probe clears on the applied ack | `Send` guard | to be written (T11/T14): the next scene is not sent on a pong, nor when the wait is exhausted (`review-r7-silent.md` F3, `review-r7-invariants.md` F-3). The code today releases on a pong (O6) |
| P22 The death queue drops nothing while the replicator is away | `Charge` with `card(dom(dqown)) = 2` | to be written (T11/T14): more deaths than the queue's current bound of 64 are all charged (`review-r7-invariants.md` F-4) |
| P23 A crash with no dial live: the carried set outlives it | `HubEnd; DisplayEndDown; Redial` | to be written (T11/T14) |
| P24 The integration display behaves like the real one | all | to be written (T11/T14): `Responder` acks the poison scene only after a swap that never comes, then hangs up; `test_crash_quarantine.py` quarantines at the threshold against it |
| P25 A probe retire of a live display that holds the culprit, then a crash on the next dial | `Send; Install; Unresponsive; DiscoverUnrCharge; Redial; CrashFrame; DiscoverCharge; Charge` | to be written (T11/T14): the keepalive (or isolation probe) retires the dial with `unresponsive`, the display, still alive, crashes painting the held scene on the next dial; assert the culprit is charged on the probe dial and again through the carried set on the crash dial, and the innocent scene on the crash dial is struck once. `tests/domain/test_retire_cause.py::TestADialTheKeepaliveFoundUnresponsive` covers the retire cause only |
| P26 O7: the predecessor is preempted before the new dial's first scene | `Install` only on the live dial | to be written (T11/T14): a display that handles a `ConnectMessage` with the predecessor's `HubId` closes the predecessor and installs nothing from it afterwards; an unidentified socket's scene is refused with no ack |
| B1 A late reveal is not attributed | none (outside the model) | to be written (T11/T14): a test that documents the bound |
| B7 Another Hub's crash charges this Hub's ledger and carried set | none (one Hub modelled) | to be written (T11/T14): two Hubs, one display, a scene of Hub B crashes it; assert Hub A's charge is its ledger and carried set and no more |

Re-run `fuzz`, the model-check and the controls whenever the attribution path changes who
charges, from what evidence, when, or what an ack means.
