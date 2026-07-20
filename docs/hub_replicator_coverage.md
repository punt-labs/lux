# Hub Replicator: Test-Partition Coverage Audit

Companion to `docs/hub_replicator.tex`. Derives the test partitions (Test
Template Framework style) from the Z operation schemas, then maps them against
the tests that cover them, exactly as `docs/display_lifecycle_coverage.md` maps
its spec to `tests/test_socket_server.py` and `tests/test_paths.py`. The worker,
its dirty signal, and the store lock are covered by
`tests/domain/test_hub_replicator.py`, `tests/domain/test_dirty_signal.py`, and
`tests/domain/test_store_lock.py`; the two store-empty clear partitions (CL1,
CL2) are covered by the clear tool's tests in `tests/test_tools.py`, and the real
bounded-send time limit behind P3/P4 is measured by the mandatory `SO_SNDTIMEO`
probe test in `tests/test_send_timeout.py`.

The bar is that the spec's partitions are each covered by a test, not merely
that the model-check passed.

Spec-operation → design-element mapping (the design in
`docs/architecture/mcp-display-liveness.md`; concrete methods are named where
the design fixes them):

| Spec operation | Design element |
|---|---|
| `ReplaceBegin` / `ReplaceCommit` | a mutation under the store write lock: `HubDisplay.replace_scene` / `HubSceneWriter.apply`, then `replicator.mark_dirty` |
| `ClearStore` | `HubSceneWriter.clear` + `replicator.mark_cleared` |
| `Wake` / `Drain` | the worker's condition wait, the 16 ms coalesce, and the drain of the dirty set + cleared flag |
| `Snap` | the store's `SceneReader.snapshot(scene)` — a deep copy of the roots taken under the read lock |
| `SendBegin` / `SendOk` | the time-limited `show_async` send that succeeds |
| `SendStuck` | the send raising `BlockingIOError` (send timeout, `SO_SNDTIMEO`) |
| `SendDead` | the send raising `OSError` (`ECONNRESET`/`EPIPE`) |
| `Reap` / `Ensure` | `DisplayPaths().reap()` then `DisplayPaths().ensure()` + `client.close()` |
| `Remark` | `HubReplicator._remark` over `HubDisplay.live_scene_ids()`, plus a re-marked clear |
| `Reconn` | `client.close()` + reconnect on the dead-peer path |
| `ApplyClear` | the worker pushing the clear (blank) for the cycle |
| `ProcDone` | the worker returning to the condition wait |
| `DisplayWedge` / `DisplayCrash` | the display ceasing to read / the display process dying |
| `ShutdownReq` / `Flush` | luxd stopping; the worker's final bounded flush |
| `Restart` | luxd starting again |

## 1. Partitions

### ReplaceBegin(m?, s?) / ReplaceCommit(m?) — the store mutation under the write lock

| # | Partition | Expected |
|---|---|---|
| M1 | write lock free, worker not snapshotting → acquire, scene goes `vtorn` | lock taken, scene mid-replace |
| M2 | second mutator wants the lock while the first holds it | blocks until release — never two writers |
| M3 | commit installs `vlive` and marks the scene dirty in one step | dirty gains the scene; lock released |
| M4 | mutator acquires while the worker holds the read lock | not enabled until the worker releases (reader-writer exclusion) |
| M5 | two scenes mutated across two acquire/commit pairs | both end `vlive`, both dirty |

### ClearStore — clear empties the store and sets the cleared flag

| # | Partition | Expected |
|---|---|---|
| CL1 | clear from a populated store | every scene `vempty`, cleared set |
| CL2 | clear while the display is down | store empties regardless — clear never depends on the display |
| CL3 | clear then a `show` of one scene, both before the worker drains | **clear-first: the show survives (display shows the new scene)** |
| CL4 | a `show` then clear, both before the worker drains | display ends blank; store empty |

### Wake / Drain — coalescing and the atomic take of dirty + cleared

| # | Partition | Expected |
|---|---|---|
| D1 | idle worker, nothing dirty and not cleared | stays asleep (Wake not enabled) |
| D2 | **many marks of one scene before the drain** | **one batch entry — coalesced to a single push** |
| D3 | marks of two scenes before the drain | both drained in one batch |
| D4 | a mark that lands after the drain | carried to the next cycle, not this one |
| D5 | drain takes the dirty set and the cleared flag together | dirty cleared to empty; cleared carried for the cycle |

### Snap — snapshot the latest store value under the read lock

| # | Partition | Expected |
|---|---|---|
| S1 | read lock free (no writer) → copy the scene's current value | snapshot equals the store's latest committed value |
| S2 | **a mutator holds the write lock (`vtorn`)** | **Snap not enabled — the worker never copies a torn value** |
| S3 | pending clear not yet applied | Snap not enabled until the clear is pushed (clear-first) |
| S4 | scene mutated many times before Snap | the value copied is the newest, not a mid-burst one |

### SendBegin / SendOk / SendStuck / SendDead — the time-limited send

| # | Partition | Expected |
|---|---|---|
| P1 | release the read lock, then take the client lock | the two locks are never held together |
| P2 | display up → send succeeds | display now shows the copied value; scene leaves the batch |
| P3 | **display wedged → `BlockingIOError`** | **client lock released within the time limit; go to reap** |
| P4 | **display dead → `OSError`** | **client lock released; go to reconnect** |
| P5 | display wedges after the snapshot but before the send | detected as `BlockingIOError` on the send |
| P6 | a mutator runs while the worker is stuck in the send | the mutator makes progress — never blocked on the send |

### Reap / Ensure / Remark — reap and respawn after a send timeout

| # | Partition | Expected |
|---|---|---|
| K1 | wedged display is killed before a fresh one is started | respawn follows the kill — never two live displays |
| K2 | **respawn with live scenes in the store** | **every live scene re-marked; display repainted to the store's state** |
| K3 | **respawn with an empty store** | nothing to repaint; display stays empty, consistent |
| K4 | the scene that was in flight when the send failed | re-covered by the re-mark of every live scene |
| K5 | a mutation lands during reap/respawn | picked up after respawn; latest state pushed |
| K6 | `client.close()` after respawn | the next send binds the fresh connection, same cycle |

### Reconn — the dead-peer path

| # | Partition | Expected |
|---|---|---|
| RC1 | **`OSError` → close and reconnect, no kill** | connection re-established; nothing terminated |
| RC2 | the in-flight scene on the dead-peer path | re-queued so nothing drained is dropped |
| RC3 | `OSError` where the peer process is truly gone (fresh empty display) | **must re-mark every live scene, as the reap path does — else a lost update** (see spec §Verification) |
| RC4 | `OSError` on a cleared cycle's send, then a same-display reconnect | the consumed clear is re-marked; the retry blanks then repaints, never leaving the old scene on screen |

### Recovery resilience — the recovery step itself fails

These partitions extend the spec pending the jms model extension for the amended
recovery semantics; each is covered against the real worker.

| # | Partition | Expected |
|---|---|---|
| RR1 | reap/ensure raises (an unspawnable display) or the send raises a non-socket error | the drained batch is restored (re-marked) and the worker backs off, so nothing is lost and the worker never spins |
| RR2 | the display recovers on the retry after a transient respawn failure | the restored batch repaints once the display is back |

### ApplyClear / ProcDone — ending the cycle

| # | Partition | Expected |
|---|---|---|
| E1 | **cleared cycle blanks before repainting the batch** | a show coalesced after the clear survives |
| E2 | clear pushed with an empty batch | display blanked; worker idle |
| E3 | batch drained, no clear | worker returns to the wait |

### DisplayWedge / DisplayCrash — display failure detection

| # | Partition | Expected |
|---|---|---|
| F1 | display stops reading while up | next send raises `BlockingIOError` |
| F2 | display process dies while up | next send raises `OSError` |
| F3 | display fails while nothing is dirty | no send, no spurious recovery |

### ShutdownReq / Flush / Restart — clean shutdown

| # | Partition | Expected |
|---|---|---|
| SH1 | **shutdown with pending dirty scenes** | **one final bounded flush, then stop** |
| SH2 | shutdown with a stuck display | the final send fails within the time limit; shutdown continues |
| SH3 | shutdown with nothing pending | stop immediately |
| SH4 | luxd restarts after a stop | fresh idle state |

## 2. Coverage table

Each partition names the test that exercises it against the real mechanism
(fake display ports, real store and locks), the same discipline the
display-lifecycle audit applied.

| Partition | Covering test | Status |
|---|---|---|
| M1 | test_hub_replicator::test_the_worker_snapshot_waits_for_a_mutation_to_commit | COVERED |
| M2 | test_store_lock::test_a_second_thread_blocks_while_the_lock_is_held | COVERED |
| M3 | test_hub_replicator::test_a_dirty_scene_is_sent_to_the_display | COVERED |
| M4 | test_hub_replicator::test_the_worker_snapshot_waits_for_a_mutation_to_commit | COVERED |
| M5 | test_dirty_signal::test_two_scenes_drain_in_one_batch | COVERED |
| CL1 | test_tools::TestClearTool::test_clear_empties_hub_store_and_marks_cleared | COVERED |
| CL2 | test_tools::TestClearIsDisplayIndependent::test_clear_empties_the_store_and_signals_a_blank | COVERED |
| CL3 | test_hub_replicator::test_clear_is_sent_before_the_batch | COVERED |
| CL4 | test_hub_replicator::test_a_show_then_clear_ends_blank | COVERED |
| D1 | test_dirty_signal::test_an_idle_signal_blocks_until_a_mark_arrives | COVERED |
| D2 | test_dirty_signal::test_many_marks_of_one_scene_coalesce_to_a_single_entry | COVERED |
| D3 | test_dirty_signal::test_two_scenes_drain_in_one_batch | COVERED |
| D4 | test_dirty_signal::test_a_mark_after_the_drain_is_carried_to_the_next_cycle | COVERED |
| D5 | test_dirty_signal::test_drain_takes_dirty_and_cleared_together_and_resets_both | COVERED |
| S1 | test_hub_replicator::test_a_dirty_scene_is_sent_to_the_display | COVERED |
| S2 | test_hub_replicator::test_the_worker_snapshot_waits_for_a_mutation_to_commit | COVERED |
| S3 | test_hub_replicator::test_clear_is_sent_before_the_batch | COVERED |
| S4 | test_hub_replicator::test_a_dirty_scene_is_sent_to_the_display | COVERED |
| P1 | test_hub_replicator::test_a_mutator_makes_progress_while_the_worker_is_stuck_sending | COVERED |
| P2 | test_hub_replicator::test_a_dirty_scene_is_sent_to_the_display | COVERED |
| P3 | test_hub_replicator::test_a_wedged_display_is_reaped_respawned_and_repainted | COVERED |
| P4 | test_hub_replicator::test_a_dead_peer_reconnects_without_reaping | COVERED |
| P5 | test_hub_replicator::test_a_wedged_display_is_reaped_respawned_and_repainted | COVERED |
| P6 | test_hub_replicator::test_a_mutator_makes_progress_while_the_worker_is_stuck_sending | COVERED |
| K1 | test_hub_replicator::test_a_wedged_display_is_reaped_respawned_and_repainted | COVERED |
| K2 | test_hub_replicator::test_a_wedged_display_is_reaped_respawned_and_repainted | COVERED |
| K3 | test_hub_replicator::test_recovery_of_an_emptied_store_repaints_nothing | COVERED |
| K4 | test_hub_replicator::test_a_wedged_display_is_reaped_respawned_and_repainted | COVERED |
| K5 | test_hub_replicator::test_a_mutation_during_recovery_is_repainted_after_respawn | COVERED |
| K6 | test_hub_replicator::test_a_wedged_display_is_reaped_respawned_and_repainted | COVERED |
| RC1 | test_hub_replicator::test_a_dead_peer_reconnects_without_reaping | COVERED |
| RC2 | test_hub_replicator::test_a_dead_peer_reconnects_without_reaping | COVERED |
| RC3 | test_hub_replicator::test_a_dead_peer_reconnects_without_reaping | COVERED |
| RC4 | test_hub_replicator::test_a_dead_peer_recovery_re_marks_a_consumed_clear | COVERED |
| RR1 | test_hub_replicator::test_a_recovery_failure_restores_the_batch_and_retries | COVERED |
| RR2 | test_hub_replicator::test_a_recovery_failure_restores_the_batch_and_retries | COVERED |
| E1 | test_hub_replicator::test_clear_is_sent_before_the_batch | COVERED |
| E2 | test_hub_replicator::test_a_clear_with_no_batch_only_blanks | COVERED |
| E3 | test_hub_replicator::test_a_dirty_scene_is_sent_to_the_display | COVERED |
| F1 | test_hub_replicator::test_a_wedged_display_is_reaped_respawned_and_repainted | COVERED |
| F2 | test_hub_replicator::test_a_dead_peer_reconnects_without_reaping | COVERED |
| F3 | test_dirty_signal::test_an_idle_signal_blocks_until_a_mark_arrives | COVERED |
| SH1 | test_hub_replicator::test_shutdown_flushes_a_pending_scene_then_stops | COVERED |
| SH2 | test_hub_replicator::test_shutdown_with_a_stuck_display_does_not_reap | COVERED |
| SH3 | test_dirty_signal::test_stop_with_nothing_pending_returns_shutting_at_once | COVERED |
| SH4 | test_hub_replicator::test_a_fresh_replicator_after_a_stop_starts_idle_and_works | COVERED |

## 3. Merge-critical partitions

These are the partitions that encode the exact defects the model proves the
design closes or the design must still fix. They are the ones an implementation
must not ship without.

- **S2 — the torn read.** A mutator holds the write lock (`vtorn`) and the
  worker's snapshot must not fire. This is the store-lock reason for being; the
  model's fidelity variant (spec §Fidelity) makes the torn read reachable when
  the read-lock exclusion is removed. The test stands up a mutation mid-replace
  and asserts the worker's snapshot blocks until the write lock releases, and
  never copies a half-updated tree.
- **P3 / P4 — the two send failures.** `BlockingIOError` and `OSError` are
  handled differently (reap-respawn versus reconnect) and are caught in that
  order because `BlockingIOError` is an `OSError`. A probe test must confirm the
  real send time limit is at most about 2.5 s on the CI machine, because the
  bytes packed for `SO_SNDTIMEO` do not mean the same limit on every platform.
- **P6 — agent-path liveness.** A mutator completes a full replace while the
  worker is stuck sending to a wedged display. This is the whole point of the
  change: the 38-minute freeze cannot recur because no mutator waits on the
  send.
- **K2 / K4 — no lost update across respawn.** A fresh display is empty, so
  every live scene is re-marked; the scene in flight when the send failed is
  re-covered. Without the re-mark the display stays stale.
- **CL3 / E1 — clear-first ordering.** A `clear` immediately followed by a
  `show` must leave the new scene on screen. The spec blanks before repainting;
  model-checking the design document's stated order (blank after the batch)
  finds the lost update (spec §Verification). The implementation must blank
  first, and the design document should be amended.
- **RC3 — dead-peer re-mark.** If a real `OSError` means the display process is
  gone, the reconnect path must re-mark every live scene, not just re-queue the
  one in flight. The spec models the charitable case (a live display whose
  rendered state survives); the implementation must confirm which case holds and
  re-mark if the display comes back empty.
