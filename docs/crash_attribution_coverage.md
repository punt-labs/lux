# Crash attribution: model results and coverage audit

Spec: [crash_attribution.tex](./crash_attribution.tex). Controls:
[redial_only](./crash_attribution_redial_only_buggy.tex),
[idle_stop](./crash_attribution_idle_stop_buggy.tex). Governs
`src/punt_lux/domain/hub/{batch_sender,recovery,display_connection,dial_generation,
reply_sink,liveness_probe,replicator}.py`. Ruling modelled: T10 (the death of a dial is
charged from that dial's own ack ledger, whoever discovers it; a Hub-ended dial and an
empty ledger charge nothing). Origin: the recurrence of attribution defects in final
review rounds 4, 5 and 6 (`review-r6-silent.md` F1, `review-r6-code.md` F1).

## Invariants (negated goals; never schema conjuncts)

| Id | Statement | By |
|---|---|---|
| A1 | A crash loop of a poison scene reaches quarantine after `thr` settled poison deaths, whichever party discovers each | the charge is made at every discovery and every redial, from the ledger |
| A2 | No scene is charged for a death on a dial it was never written to, or was acked on | ledger = written minus acked, per dial |
| A3 | A Hub-ended dial charges no scene | guard `ended = edisp` on both charging steps (tautology of the design) |
| A4 | Each dial's death is charged at most once | guard `cur not in settled`, and settling (tautology of the design) |

A3 and A4 are tautologies of the fixed design (no fixed operation violates them); their
content is the guards, and the code must have the same guards: the Hub-end check before
classifying a write error (code F1), and the charge-once memory keyed by dial.

## Bounds, and why they reach the defects

`maxDial = 2`, `maxScene = 2`, `thr = 2`, `poison = 1`, discoverers `drepl | dother`.
Both controls reach their violation inside these bounds (traces below), so the bounds
reach the defects. Two dials: a death must be discovered after a redial. Two scenes: one
innocent scene to be wrongly charged. Threshold two: one death is not yet a quarantine,
so the loop has a length. The fixed design was also run at `maxDial = 3`, `maxScene = 3`
(a scratch copy) to show the result does not depend on the smallest carrier.

## Results

`fuzz` clean on each of the three files separately. `probcli` at
`/home/jfreeman/Applications/ProB/probcli`, run one at a time on scratch copies under
`.tmp/ca/`; all runs were small (the largest took 106 s; `free -g` unchanged at
about 15 GB used throughout).

```text
fixed, maxDial 2, maxScene 2:  -model_check -coverage -p MAX_OPERATIONS 100 -goal "<A1 or A2 or A3 or A4>"
   -> 373 states, 711 transitions, no counter example, ALL states visited,
      deadlocked:0, UNCOVERED_OPERATIONS (0) of 11
fixed, maxDial 3, maxScene 3:  same
   -> 83553 states, 161467 transitions, no counter example, ALL states visited,
      deadlocked:0, UNCOVERED_OPERATIONS (0) of 11   (106 s)
```

Non-vacuity (goal **found** on the fixed design, `-model_check -nodead -bf -goal`):

| Goal | Steps / states |
|---|---|
| `strikes(1) = 2` (poison quarantined) | found, 171 states |
| a settled Hub-ended dial with a non-empty ledger | found, 22 states |
| a settled display-ended dial with an empty ledger (idle stop) | found, 13 states |
| a charge made while another scene was also written | found, 40 states |

Controls (`-model_check -nodead -bf -goal`):

| Control | A1 | A2 | A3 | A4 | Shortest trace |
|---|---|---|---|---|---|
| `redial_only_buggy` | **found** (208 states) | not found (556) | not found | not found | `RedialQuiet; Send(1); DisplayEnd; RedialQuiet(dother); Send(1); DisplayEnd; DiscoverCharge(drepl)`: first death healed by a non-replicator redial and discarded; the poison scene has one strike after two poison deaths. This is silent F1. |
| `idle_stop_buggy` | **found** (168 states) | **found** (30 states) | not found (362) | not found | A2: `RedialQuiet; DisplayEnd; RedialBlame; SendBlamed(1)`: a scene never written to the dead dial is charged for it. This is the idle-stop defect, and code F1's wrong-blame shape. A1: `RedialQuiet; Send(1); DisplayEnd; RedialBlame; SendBlamed(1); DisplayEnd; DiscoverBlame`. |

What T10 does not cover, by construction: a death that the Hub retires first (cause
`hub`) is never charged, even when the display had in fact died. DES-102 accepts that
trade (an unresponsive dial is charged only when the display ends it).
An innocent scene written alongside the poison scene in the same dial takes the same
strike; isolation after the first charge narrows later deaths to one scene.

## Partitions and the tests that must cover them

Each row is a partition of the model's behaviour; a test must exist for it in the code,
driving the real components, not a fake sender that raises inside the send. A test that
stubs the mechanism is a gap.

| Partition | Model operations | Test required |
|---|---|---|
| P1 Display death discovered by the replicator's own send | `DisplayEnd; RedialCharge` / `DiscoverCharge(drepl)` | existing quarantine tests; keep |
| P2 Display death discovered by a non-replicator redial (keepalive, MCP tool) between pushes | `DisplayEnd; RedialCharge(dother)` | **silent F1 regression:** a clean push, the display's end closed, the reader retires the dial, a redial from outside the sender heals it; repeat `thr` times; assert the scene is quarantined and the strike count reached `thr` |
| P3 Display death discovered by the reader or keepalive with no redial yet | `DisplayEnd; DiscoverCharge(dother)` | assert the charge is made at discovery, and the later redial does not charge it again |
| P4 Charge once per dial, however many parties discover | `DiscoverCharge` then `RedialQuiet` (settled) | two discoverers on one dial: exactly one strike per scene in its ledger; a new dial's death is charged again |
| P5 Hub-ended dial, ledger non-empty | `HubEnd; DiscoverQuiet`, `RedialQuiet` | **code F1 regression:** a writer blocked in `sendall`, the dial retired with cause `hub` from a second thread; assert `push` raises with a `HubRetiredError` cause and no scene is charged. Same for the inline read |
| P6 Display-ended dial, empty ledger (idle stop, or all acked) | `DisplayEnd; DiscoverQuiet`, `RedialQuiet` | a stop while idle, then a redial and a send: assert the scene sent next has no strike |
| P7 Acked scene is not a suspect | `Ack` then `DisplayEnd` | a scene acked on the dial, a later scene unacked at the death: assert only the unacked scene is charged |
| P8 Scene written to a previous dial only | `Send` on dial 1, `DisplayEnd`, redial, `Send` on dial 2 | assert a scene written only to dial 2 is not charged for dial 1's death (A2) |
| P9 Isolation narrows the suspect set | `Send` guard `strikes > 0 implies ledger = empty` | after the first charge, scenes go one at a time; a death in isolation charges one scene |
| P10 Quarantine boundary | `strikes = thr` leaves `dirty` | the redial after the quarantining charge does not re-mark the quarantined scene; a quarantined scene is never sent |
| P11 Deadlock-freedom and the last dial | `Halt` | the replicator with no redial budget left settles the last dial's death |

Re-run `fuzz`, the model-check and the controls whenever the attribution path changes
who charges, from what evidence, or when.
