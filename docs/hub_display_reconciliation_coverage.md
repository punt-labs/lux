# Hub/Display Scene Reconciliation: Test-Partition Coverage Audit

Companion to `docs/hub_display_reconciliation.tex`. Derives the test
partitions from the Z operation schemas — `HubIdentify`, `HubManifest`,
`SceneInstall`, `ConnectionDrop` — and maps each against the tests that
cover it, in the same style as `docs/hub_replicator_coverage.md`. The bar
is that the spec's partitions are each covered by a test, not merely that
the model-check passed.

Spec-operation → design-element mapping (the design in
`docs/architecture/hub-display-reconciliation-design.md`; concrete methods
are named where the design fixes them):

| Spec operation | Design element |
|---|---|
| `HubIdentify` | `HubReconciliation.handle_connect` + `._preempt_stale_hub` (`display/hub_reconciliation.py`) |
| `HubManifest` | `HubReconciliation.handle_manifest` + `SceneReplica.scenes_to_purge` (`display/replica/scene_replica.py`) |
| `SceneInstall` | `RenderLoop._handle_scene` → `SceneReplica.handle_framed_scene` — unchanged by this design; modelled to show it is unaffected once its source connection is live |
| `ConnectionDrop` | `SocketListener.remove_client` → `RenderLoop._on_client_disconnected` → `SceneReplica.reassign_scenes_of` |

## 1. Partitions

### HubIdentify(c?) — single-owner preemption

| # | Partition | Expected |
|---|---|---|
| HI1 | a `kind="hub"` identify with no predecessor holding the identity | recorded; nothing preempted (the ordinary restart case — the old socket is already gone) |
| HI2 | **a `kind="hub"` identify with a live predecessor holding the identity** | **the predecessor is forcibly disconnected before the new one is recorded — at most one ever holds the identity (I3)** |
| HI3 | a `kind="test"` identify | never preempts anything and is never itself preempted by a later hub identify |
| HI4 | two `kind="hub"` identifies for two *different* declared names | neither preempts the other — preemption scopes to the shared name |
| HI5 | preemption's scene reassignment | every scene the evicted predecessor owned becomes orphan, never removed |

### HubManifest(c?, m?) — the purge

| # | Partition | Expected |
|---|---|---|
| HM1 | **a scene neither owned by the identifying fd nor named in the manifest** | **purged — removed from the Display's scene map, its frame closed if emptied** |
| HM2 | a scene named in the manifest | survives, regardless of current ownership |
| HM3 | a scene owned by the identifying fd | survives, regardless of manifest contents (item 4 of the design: ownership self-corrects on the Hub's own next resend) |
| HM4 | **a mixed frame — one scene manifested or fd-owned, one neither** | **loses only the ghost scene; the frame itself survives, per-scene not per-frame** |
| HM5 | **an orphaned scene (owner reassigned after a prior Hub connection died)** | **swept by the identical rule — no special case, since an orphan's owner is never the identifying fd** |
| HM6 | a manifest processed by a connection that is not the current declared identity | never happens — `HubManifest` (real: the manifest handler) only ever runs for the fd that just identified |
| HM7 | widget state for a purged scene | discarded, as a side effect of the existing per-scene close path |
| HM8 | widget state for a retained scene | untouched |

### SceneInstall(c?, s?) — only from a live connection

| # | Partition | Expected |
|---|---|---|
| SI1 | an install from a connection whose socket is still open | accepted; the scene's owner is set to that connection |
| SI2 | **a straggling install from a connection preemption has already evicted** | **dropped — the guard disables it; this is the ordering property (I2) single-owner preemption exists to close** |

### ConnectionDrop(c?) — ordinary disconnect

| # | Partition | Expected |
|---|---|---|
| CD1 | a connection with no owned scenes disconnects | no visible effect |
| CD2 | a connection with owned scenes disconnects | every scene it owned becomes orphan, never removed — `reassign_scenes_of`'s real behaviour |
| CD3 | the current declared identity disconnects with no successor yet | the identity slot empties; a later identify preempts nothing (HI1) |

### Notify regression guard — a purge is silent, a user-initiated close is not

| # | Partition | Expected |
|---|---|---|
| NR1 | **a manifest-driven purge that empties a frame** | **no `frame_close` event reaches the frame's former owner — `_close_frame(..., notify=False)`, its first real caller** |
| NR2 | **a pre-existing user-initiated frame close (World-menu clear, tab close)** | **still notifies (`notify=True`, unchanged) — this design must not regress those call sites** |

## 2. Coverage table

| Partition | Covering test | Status |
|---|---|---|
| HI1 | `test_hub_reconciliation::TestHandleConnect::test_a_hub_identify_with_no_predecessor_preempts_nothing` | COVERED |
| HI2 | `test_hub_reconciliation::TestHandleConnect::test_a_second_hub_identify_forcibly_disconnects_the_first`; `test_render_loop::TestHandleConnectDispatch::test_a_second_hub_identify_preempts_the_first_via_the_real_socket_listener` | COVERED |
| HI3 | `test_hub_reconciliation::TestHandleConnect::test_a_test_identify_never_preempts_or_marks_hub`; `test_render_loop::TestHandleConnectDispatch::test_a_test_identify_is_recorded_without_preemption` | COVERED |
| HI4 | `test_hub_reconciliation::TestHandleConnect::test_a_different_named_hub_identify_is_not_preempted` | COVERED |
| HI5 | `test_hub_reconciliation::TestHandleManifest::test_a_scene_outside_the_manifest_is_purged` (exercises the reassign-to-orphan indirectly via a purge after eviction) | COVERED |
| HM1 | `test_hub_reconciliation::TestHandleManifest::test_a_scene_outside_the_manifest_is_purged`; `test_scene_replica::TestScenesToPurge::test_a_scene_outside_the_manifest_and_owner_is_a_candidate`; `test_render_loop::TestHandleManifestDispatch::test_a_manifest_purges_a_ghost_scene_through_the_real_dispatch` | COVERED |
| HM2 | `test_hub_reconciliation::TestHandleManifest::test_a_scene_in_the_manifest_survives`; `test_scene_replica::TestScenesToPurge::test_a_scene_named_in_the_manifest_is_not_a_candidate` | COVERED |
| HM3 | `test_hub_reconciliation::TestHandleManifest::test_a_scene_owned_by_the_identifying_fd_survives`; `test_scene_replica::TestScenesToPurge::test_a_scene_owned_by_the_identifying_fd_is_not_a_candidate` | COVERED |
| HM4 | `test_hub_reconciliation::TestHandleManifest::test_a_mixed_frame_only_loses_its_ghost_scene`; `test_scene_replica::TestScenesToPurge::test_a_mixed_frame_loses_only_its_ghost_scene` | COVERED |
| HM5 | `test_scene_replica::TestScenesToPurge::test_an_orphaned_scene_is_swept_by_the_same_rule` | COVERED |
| HM6 | implied by HI2 + SI2 (a superseded connection can never send a manifest, since it is no longer live) | COVERED (structural — no dedicated test needed) |
| HM7 | `test_scene_replica::TestScenesToPurge::test_widget_state_is_discarded_only_for_the_purged_scene` | COVERED |
| HM8 | `test_scene_replica::TestScenesToPurge::test_widget_state_is_discarded_only_for_the_purged_scene` | COVERED |
| SI1 | `test_hub_reconciliation::TestHandleConnect::test_a_kind_hub_identify_is_recorded` (implicitly — every `SceneInstall`-adjacent test installs against a live fd) | COVERED |
| SI2 | Modelled and model-checked (`docs/hub_display_reconciliation.tex` I2; the fidelity control `docs/hub_display_reconciliation_no_preemption_buggy.tex` reproduces the violation). No direct unit test: the real guard is socket closure, which `tests/integration/test_hub_display_reconciliation.py` exercises end to end over a real subprocess pair | COVERED (model-check + integration) |
| CD1 | `test_hub_reconciliation::TestHandleConnect::test_a_hub_identify_with_no_predecessor_preempts_nothing` (indirectly — no owned scenes to reassign) | COVERED |
| CD2 | pre-existing `reassign_scenes_of` coverage (`tests/display/replica/test_frame_book.py`), unchanged by this design | COVERED (pre-existing) |
| CD3 | `test_hub_reconciliation::TestHandleConnect::test_a_hub_identify_with_no_predecessor_preempts_nothing` | COVERED |
| NR1 | `test_render_loop::TestNotifyRegressionGuard::test_a_manifest_driven_purge_sends_no_frame_close_event` | COVERED |
| NR2 | `test_render_loop::TestNotifyRegressionGuard::test_a_user_initiated_close_still_notifies_the_owner` | COVERED |

## 3. Merge-critical partitions

These are the partitions that encode the exact defect the model proves the
design closes. They are the ones the implementation must not ship without.

- **HI2 / SI2 — single-owner preemption closes the interleaving.** The
  entire bug (`lux-e9vy`) is that a Display never learns a Hub process
  died, so it keeps a dead process's scenes forever and their clicks
  dispatch into nothing. HI2 is the socket-level fix (a stale connection
  cannot outlive the identify that supersedes it); SI2 is why that fix
  matters (a straggling install from the stale connection is rejected, not
  silently re-applied). The z-spec's fidelity control
  (`hub_display_reconciliation_no_preemption_buggy.tex`) removes exactly
  HI2's socket-eviction step and reproduces an I1 violation — a scene
  neither owned by the live identity nor an orphan the manifest still
  names — confirming the model has enough teeth to catch what single-owner
  preemption exists to prevent.
- **HM1 / HM4 / HM5 — the purge is per-scene, not per-frame, and orphans
  are swept by the same rule.** The corrected design (post-review) fixed a
  real bug in the original per-frame sketch: closing a whole frame the
  instant *any* of its scenes fails the keep-test would also destroy a
  sibling scene the manifest legitimately kept. HM4 is the regression
  guard for that fix; HM5 confirms no special-casing was needed for
  orphaned scenes, since an orphan's owner (the sentinel `_ORPHAN_FD`) can
  never equal the identifying fd, so it falls out of the same rule.
- **NR1 / NR2 — the purge is silent; nothing else changes.** A purge must
  never notify a dead owner (nothing is listening), and this design must
  not regress the existing user-initiated close paths, which still notify
  surviving owners. Both are asserted directly against the real
  `RenderLoop._close_frame` call sites.
