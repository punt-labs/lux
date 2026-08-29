# Frame TTL Expiry: Test-Partition Coverage Audit

Companion to `docs/frame_expiry.tex`. Derives the test partitions from the Z
operation schemas and maps each against the test that covers it, the same way
`docs/hub_replicator_coverage.md` and `docs/display_lifecycle_coverage.md` map
their specs to code. The bar is that every partition is covered by a test, not
merely that the model-check passed.

The model abstracts real time to three deadline tokens (`dnone`, `dfuture`,
`dpast`); the code realises the tokens with a monotonic clock, injected as a fake
in the tests so time is a value the test sets, not a wall it waits on.

## Spec-operation → design-element mapping

The design is `docs/architecture/target/target.md` (Hub-authoritative; a re-show
is a whole-UI resend); the concrete methods live in
`src/punt_lux/domain/hub/frame_expiry.py` (the deadlines),
`src/punt_lux/domain/hub/frame_lifecycle.py` (arm/expire/tear-down under the store
lock), `src/punt_lux/domain/hub/expiry_sweep.py` (the event-loop tick), and
`src/punt_lux/domain/hub/scene_snapshot.py` (the replicator's post-blank reclaim).

| Spec operation | Design element |
|---|---|
| `ReShow` | `HubDisplay.show_scene(..., ttl_seconds=t)` — install roots + `FrameLifecycle.present(...)` (records the presentation and calls `FrameExpiry.set_deadline(frame, t)`), one write lock |
| `ReShowNoTtl` | the same `show_scene` with `ttl_seconds=None` → `FrameLifecycle.present(...)` → `FrameExpiry.set_deadline(frame, None)` → `FrameExpiry.disarm` (frame made permanent) |
| `TimePass` | the monotonic clock advancing past an armed deadline (a real duration in the code; a `FakeClock.advance` in tests) |
| `Expire` | `FrameLifecycle.expire_due` → `FrameExpiry.due_frames` + `SubtreeRemover.drop_scene_roots` + `FrameExpiry.disarm`, one write lock; the `ExpirySweep` tick invokes it and marks the scenes dirty |
| `Reclaim` | `SceneReader.reclaim_if_rootless` → `FrameLifecycle.forget` — the replicator's post-blank reclaim: it drops the presentation and `FrameExpiry.disarm`s the frame once it empties |

## Operation partitions and their tests

| Partition | Meaning | Covering test |
|---|---|---|
| RS1 | a TTL show arms a future deadline | `test_frame_expiry.py::test_armed_frame_becomes_due_only_after_its_deadline`; `test_hub_display_ttl.py::test_a_ttl_frame_expires_its_scene_after_the_deadline` |
| RS2 | a re-show before the deadline replaces (refreshes) it | `test_frame_expiry.py::test_reshow_with_new_ttl_replaces_the_deadline`; `test_hub_display_ttl.py::test_a_reshow_with_a_new_ttl_refreshes_the_deadline` |
| RS3 | a re-show without a TTL clears the deadline (permanent) | `test_frame_expiry.py::test_reshow_without_ttl_makes_the_frame_permanent`; `test_hub_display_ttl.py::test_a_reshow_without_a_ttl_makes_the_frame_permanent` |
| NT1 | a frame never armed never expires | `test_frame_expiry.py::test_unarmed_frame_is_never_due`; `test_hub_display_ttl.py::test_a_frame_without_ttl_never_expires` |
| TP1 | before the deadline nothing is due | `test_frame_expiry.py` (advance-4.9); `test_hub_display_ttl.py::test_expire_due_is_empty_before_the_deadline`; `test_expiry_sweep.py::test_sweep_marks_nothing_before_the_deadline` |
| EX1 | a due frame is a peek, claimed until disarmed, and its roots torn down | `test_frame_expiry.py::test_due_frames_is_a_peek_until_disarmed`; `test_hub_display_ttl.py::test_a_ttl_frame_expires_its_scene_after_the_deadline`; `test_expiry_sweep.py::test_sweep_marks_and_tears_down_a_due_frame` |
| EX2 | expiry removes every scene the frame holds | `test_hub_display_ttl.py::test_expire_due_removes_every_scene_the_frame_holds` |
| EX3 | only the due frames are taken, others keep their deadlines | `test_frame_expiry.py::test_due_frames_takes_only_the_frames_that_are_due` |
| RC1 | the replicator's post-blank reclaim disarms an emptied frame; a reused frame id inherits no stale deadline | `test_hub_display_ttl.py::test_reclaiming_a_blanked_ttl_frame_disarms_its_deadline`; `test_hub_display_ttl.py::test_a_reused_frame_id_does_not_inherit_a_reclaimed_frames_deadline`; `test_hub_display_ttl.py::test_forget_disarms_the_ttl_once_the_frame_empties` |
| WAIT1 | the sweep waits to the soonest deadline, idles when none armed, clamps a passed deadline to zero | `test_frame_expiry.py::test_seconds_until_next_*`; `test_expiry_sweep.py::test_next_wait_*` |
| RUN1 | the sweep loop retires an armed frame end to end, and survives a faulting cycle | `test_expiry_sweep.py::test_run_sweeps_until_cancelled`; `test_expiry_sweep.py::test_run_survives_a_raising_sweep_cycle`; `test_expiry_sweep.py::test_run_survives_a_raising_wait_computation`; `test_expiry_sweep.py::test_run_expires_a_real_frame_end_to_end` (integration, real monotonic clock) |

## The safety invariant I1

I1 — *a frame with a future deadline is always shown* (`docs/frame_expiry.tex`) —
is the property that requires `ReShow` to install the roots and arm the deadline
as one atomic step under the store lock, and that requires *every* removal path
(`Expire`, `Reclaim`) to disarm the deadline as it drops the roots.
It is proved by reachability model-check: the negating state (a future deadline
with absent roots) is unreachable from `Init` over the bounded carrier (all 16
states visited, goal never satisfied). Two fidelity variants reach it, each
reproducing a real defect: splitting `ReShow` into two steps (the arm/expiry race),
and `ReclaimNoDisarmBAD` — a reclaim that drops the roots but leaves the deadline
armed (the stale-deadline-after-reclaim defect), whose one-step trace `ReShow` then
non-disarming `Reclaim` lands directly in the negating state. The code enforces the
atomicity by arming inside `show_scene`'s write lock (`HubDisplay.show_scene`) and
by routing the reclaim through `FrameLifecycle.forget` (`SceneReader.reclaim_if_rootless`),
which disarms as it forgets. Re-run the goal check whenever `frame_lifecycle.py`,
`scene_snapshot.py`, or `hub_display.py`'s `show_scene` changes.
