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
lock), and `src/punt_lux/domain/hub/expiry_sweep.py` (the event-loop tick).

| Spec operation | Design element |
|---|---|
| `ReShow` | `HubDisplay.show_scene(..., ttl_seconds=t)` — install roots + record presentation + `FrameLifecycle.set_deadline(frame, t)`, one write lock |
| `ReShowNoTtl` | the same `show_scene` with `ttl_seconds=None` → `FrameExpiry.disarm` (frame made permanent) |
| `TimePass` | the monotonic clock advancing past an armed deadline (a real duration in the code; a `FakeClock.advance` in tests) |
| `Expire` | `FrameLifecycle.expire_due` → `FrameExpiry.claim_due` + `SubtreeRemover.drop_scene_roots`, one write lock; the `ExpirySweep` tick invokes it and marks the scenes dirty |
| `ManualClose` | `FrameLifecycle.remove_frame(frame)` — the display `frame_close` dispatch and a whole-display clear |

## Operation partitions and their tests

| Partition | Meaning | Covering test |
|---|---|---|
| RS1 | a TTL show arms a future deadline | `test_frame_expiry.py::test_armed_frame_becomes_due_only_after_its_deadline`; `test_hub_display_ttl.py::test_a_ttl_frame_expires_its_scene_after_the_deadline` |
| RS2 | a re-show before the deadline replaces (refreshes) it | `test_frame_expiry.py::test_reshow_with_new_ttl_replaces_the_deadline`; `test_hub_display_ttl.py::test_a_reshow_with_a_new_ttl_refreshes_the_deadline` |
| RS3 | a re-show without a TTL clears the deadline (permanent) | `test_frame_expiry.py::test_reshow_without_ttl_makes_the_frame_permanent`; `test_hub_display_ttl.py::test_a_reshow_without_a_ttl_makes_the_frame_permanent` |
| NT1 | a frame never armed never expires | `test_frame_expiry.py::test_unarmed_frame_is_never_due`; `test_hub_display_ttl.py::test_a_frame_without_ttl_never_expires` |
| TP1 | before the deadline nothing is due | `test_frame_expiry.py` (advance-4.9); `test_hub_display_ttl.py::test_expire_due_is_empty_before_the_deadline`; `test_expiry_sweep.py::test_sweep_marks_nothing_before_the_deadline` |
| EX1 | a due frame is claimed exactly once and its roots torn down | `test_frame_expiry.py::test_claim_due_returns_each_frame_once`; `test_hub_display_ttl.py::test_a_ttl_frame_expires_its_scene_after_the_deadline`; `test_expiry_sweep.py::test_sweep_marks_and_tears_down_a_due_frame` |
| EX2 | expiry removes every scene the frame holds | `test_hub_display_ttl.py::test_expire_due_removes_every_scene_the_frame_holds` |
| EX3 | only the due frames are claimed, others keep their deadlines | `test_frame_expiry.py::test_claim_due_takes_only_the_frames_that_are_due` |
| MC1 | a manual close disarms the TTL — no stale later sweep | `test_hub_display_ttl.py::test_manual_remove_frame_disarms_the_ttl` |
| WAIT1 | the sweep waits to the soonest deadline, idles when none armed, clamps a passed deadline to zero | `test_frame_expiry.py::test_seconds_until_next_*`; `test_expiry_sweep.py::test_next_wait_*` |
| RUN1 | the sweep loop retires an armed frame end to end on a real event loop | `test_expiry_sweep.py::test_run_sweeps_until_cancelled`; `test_expiry_sweep.py::test_run_expires_a_real_frame_end_to_end` (integration, real monotonic clock) |

## The safety invariant I1

I1 — *a frame with a future deadline is always shown* (`docs/frame_expiry.tex`) —
is the property that requires `ReShow` to install the roots and arm the deadline
as one atomic step under the store lock. It is proved by reachability
model-check: the negating state (a future deadline with absent roots) is
unreachable from `Init` over the bounded carrier (all 16 states visited, goal
never satisfied), and the fidelity variant that splits `ReShow` into two steps
reaches it. The code enforces the atomicity by arming inside `show_scene`'s write
lock (`HubDisplay.show_scene`), exercised whenever a TTL show is followed by an
expiry in the tests above; there is no separate arm call that a sweep could
interleave with. Re-run the goal check whenever `frame_lifecycle.py` or
`hub_display.py`'s `show_scene` changes.
