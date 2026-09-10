# Display Linkage: Test-Partition Coverage Audit

Companion to `docs/display_linkage.tex`, following the same format as
`docs/hub_replicator_coverage.md` and `docs/connection_lease_reaping_coverage.md`.
`docs/architecture/display-presence-demand-driven.md` (bead `lux-81t3.1`) is
**implemented**: every "Expected covering test" below names the actual test
that satisfies the partition, per the design document's own §10 item 11
("Tests"). One partition (L22 — the prober's independence from the
replicator's own phase while both run concurrently against one registry) has
no dedicated covering test yet; that gap is called out in its row rather than
misreported as covered.

The bar, as with every other coverage audit in this repository, is that the
spec's partitions are each covered by a test, not merely that the
model-check passed.

## Model-check results and independent evaluation

`jra` independently re-ran the full suite and confirmed every result — fuzz
clean, all 8 invariants and deadlock-freedom holding, both mandatory
fidelity controls and the bonus lock-holding control reproducing exactly as
claimed — and additionally ran the deadlock check at `DEFAULT_SETSIZE 3`
(this specification's own verification section stops at 2, per
`docs/display_lifecycle.tex`'s and `docs/hub_replicator.tex`'s convention):
24,408 states, 223,921 transitions, no counterexample — no interleaving the
larger carrier exposes that the smaller one did not. Verdict: **revise,
light** — two invariants' prose overclaimed relative to what the untimed
model actually discharges, corrected in `docs/display_linkage.tex`'s I6 and
I8 paragraphs and in design §12's own I6 (no model-structure change; every
number above is unchanged by the revision).

The two corrections, in brief: I6's reachability of `wokenEarly = set`
proves the early-wake mechanism is present, reachable, and load-bearing (its
absence is exactly fidelity control (b)) — it does not prove the design's
literal "within one `DisplayLiveness` probe tick" real-time bound, which an
untimed Z model has no clock to state. I8's "the wait never holds the lock"
holds in the degenerate sense that `regLock = held` is unreachable in *any*
state of the corrected model at all (every dial is one atomic step), not
only during the wait; the specific hazard is exercised only by fidelity
control (c), and the registry/`StoreLock` two-lock ordering is deferred to
`hub_replicator.tex`'s own I3 on the stated premise that
`wait_for_reconnect` acquires no second lock.

## Spec operation → design element mapping

| Spec operation | Design element |
|---|---|
| `PushContent` | An MCP write (`show`/`update`) landing content in `HubDisplay` — unaffected by `DisplayLinkage`, per §4's own table |
| `WithdrawContent` | A scene disposed or a session's disconnect blanking the scenes it alone held, before or after a display connects |
| `GoReachable` / `GoUnreachable` | `lux display start`/`stop`, the OS service supervisor starting the display at login, or auto-restarting it after a crash (§7) — never a Hub-initiated call |
| `GoSendOk` / `GoSendFail` | An already-connected send succeeding or hitting the `BlockingIOError`/`OSError` pair `hub_replicator.tex` fully derives; here coarsened to one flag since this spec does not re-derive which socket error fired |
| `RDialOk` | `ClientRegistry.get()` succeeding — the `linked = clear` branch is `_connect_and_reconcile` (DES-068) firing for the first time since a drop |
| `RDialFail` | `ClientRegistry.get()` raising `DisplayNotConnectedError` — the `disconnected` arm of `_CycleOutcome` (§6.1), routed through `HubReplicator._handle_disconnected` (§6.3) |
| `RWaitWoken` | `ClientRegistry.wait_for_reconnect(timeout, since_gen=...)` returning `True` — the generation counter (a monotonic `_reconnect_gen` plus a `Condition` wrapping `_lock`) replaces the earlier `Event`-based design; see the PR-465 review note under Implementer notes |
| `RWaitTimeout` | `ClientRegistry.wait_for_reconnect(timeout, since_gen=...)` returning `False` |
| `RSendCycle` | `_CycleOutcome.outcome = "clean"` — a real send succeeded, `_disconnected_backoff` and `_backoff` (wedge) both eligible to reset |
| `RSendFail` | `_CycleOutcome.outcome = "recovered"` — a connected-but-misbehaving send, healed by `SendRecovery`; the wedge backoff (`HubReplicator._backoff`, 0.1s→2.0s) advances, never the disconnected one |
| `RHeal` | `SendRecovery`'s reap/respawn/reconnect/re-mark — `docs/hub_replicator.tex`'s own `Reap`/`Ensure`/`Remark`/`Reconn`, entered and left as one step here |
| `LDialOk` / `LDialFail` | `DisplayLiveness.check_once()`'s `_probe()` outcome, paced by `_interval` (connected) or `_DISCONNECTED_PROBE_INTERVAL` (§6.4) |

## Partitions

### Content — never gated on the display

| # | Partition | Expected |
|---|---|---|
| L1 | a push lands while disconnected | content becomes live and owed; nothing about the display can disable the push |
| L2 | a push lands while connected | owed for the next delivery cycle |
| L3 | content withdrawn before any display ever connects | `DisplayLinkage` returns to `DISCONNECTED` (§4's `HELD`→`DISCONNECTED` row) |
| L4 | content withdrawn while connected | no effect on linkage; ordinary disposal |

### `DisplayLinkage.classify` — the observed four-way split

| # | Partition | Expected |
|---|---|---|
| L5 | all four combinations of `(linked, live \neq \emptyset)` | `DISCONNECTED`, `HELD`, `CONNECTED_IDLE`, `CONNECTED_ACTIVE` exactly as §4's table states, with no fifth reachable classification |

### The replicator's dial — telling "never connected" from "connected but misbehaving"

| # | Partition | Expected |
|---|---|---|
| L6 | `.get()` raises `RuntimeError` (`RDialFail`) | routed to the `disconnected` outcome; the wedge backoff (`_backoff`) is untouched; content is not lost |
| L7 | `.get()` succeeds after a prior disconnect (`RDialOk`, `linked` was `clear`) | every currently-live scene (and the menu) is marked dirty in the same step — the DES-068 reconcile, exactly once |
| L8 | `.get()` succeeds while already connected (`RDialOk`, `linked` was `set`) | an ordinary cycle start; no re-reconcile, no duplicate re-mark |

### The disconnected backoff — its own curve, its own cap

| # | Partition | Expected |
|---|---|---|
| L9 | sustained disconnection, no send ever attempted | `discBackoff` climbs strictly and reaches its own cap (2s→120s in the design) — **not** the wedge backoff's lower cap |
| L10 | a clean cycle follows a reconnect | `discBackoff` resets to base immediately, no stability window needed (§6.3: "reconnected and sent successfully" is unambiguous) |
| L11 | the tri-state outcome collapsed onto one shared backoff (fidelity control (a)) | `discBackoff` frozen, unreachable past its initial value; the shared counter plateaus at the wedge backoff's low cap instead — the model's rendering of §1's confirmed root cause |

### The interruptible wait — prompt rediscovery without a blocking sleep

| # | Partition | Expected |
|---|---|---|
| L12 | the shared event is set by **either** actor's successful dial while the replicator is parked | `RWaitWoken` fires; the replicator retries at once, `wokenEarly = set` |
| L13 | no reconnect arrives before the current delay elapses | `RWaitTimeout` fires; `wokenEarly = clear`; the event is cleared regardless (`Event.wait` then unconditional `.clear()`) |
| L14 | `RWaitWoken` deleted, only `RWaitTimeout` remains (fidelity control (b)) | a display reconnect (`reachable` set, `linked` set via the prober) while parked does **not** promptly break the replicator out — "up-to-full-delay blindness," reproduced exactly |
| L15 | the wait never holds `ClientRegistry._lock` | `regLock` stays `free` throughout `rwaitdisc` in every reachable state |
| L16 | the wait wrongly holds the lock (bonus fidelity control (c)) | the prober's own dial is starved (`regLock = held` blocks `LDialOk`/`LDialFail`'s shared guard) for as long as the replicator is parked; a display can become reachable and go unnoticed by the registry until the replicator's own (slow) retry, not a literal state-space deadlock — `RWaitTimeout` and the content operations remain always-enabled escapes |

### The two backoffs — structurally disjoint

| # | Partition | Expected |
|---|---|---|
| L17 | a disconnected-dial failure (`RDialFail`) | advances `discBackoff` only; `wedgeBackoff` is untouched by that operation's own frame |
| L18 | a connected-but-misbehaving send failure (`RSendFail`) | advances `wedgeBackoff` only; `discBackoff` is untouched by that operation's own frame |
| L19 | both counters reachable independently nonzero in one run | corroborates the mechanism is live, not dead code, and that no single step advances both |

### `DisplayLiveness` — a genuine second actor, not exempt

| # | Partition | Expected |
|---|---|---|
| L20 | the prober's own successful dial is the one that reconnects | it, too, marks the reconcile and sets the shared event (LDialOk) — "ANY successful `ClientRegistry.get()`," not only the replicator's |
| L21 | the prober's pacing while connected vs. disconnected | exactly `pconn` or `pdisc` — never a third, unnamed interval |
| L22 | the prober dials concurrently with the replicator sitting in `rwaitdisc` | not disabled by the replicator's own state — the two actors are independent |

### Process-control absence

| # | Partition | Expected |
|---|---|---|
| L23 | every operation that could plausibly touch `reachable` | only `GoReachable`/`GoUnreachable` (the environment) ever write a new value to it; every Hub-side operation's frame leaves it unchanged — the model-level form of the grep check in §10 item 11's own bullet |

## Coverage table

| Partition | Expected covering test (design §10 item 11) | Status |
|---|---|---|
| L1 | `tests/domain/test_display_linkage.py::test_classify_truth_table` (parametrized, 4 branches, no fakes) | IMPLEMENTED |
| L2 | `tests/domain/test_display_linkage.py::test_classify_truth_table` | IMPLEMENTED |
| L3 | `tests/domain/test_display_linkage.py::test_classify_truth_table` | IMPLEMENTED |
| L4 | `tests/domain/test_display_linkage.py::test_classify_truth_table` | IMPLEMENTED |
| L5 | `tests/domain/test_display_linkage.py::test_classify_truth_table` | IMPLEMENTED |
| L6 | `tests/domain/test_hub_replicator.py::test_a_dial_failure_drives_the_disconnected_branch_not_the_wedged_backoff` — a fake `ClientProvider` whose `get()` raises `DisplayNotConnectedError` drives the `disconnected` branch; asserts `_back_off()` is never invoked | IMPLEMENTED |
| L7 | `tests/test_client_registry.py::TestConnectAndReconcile` — every fresh connect through `get()` (any caller) reconciles via DES-068's one choke point | IMPLEMENTED |
| L8 | `tests/test_client_registry.py::test_get_does_not_reconnect_when_already_connected` — no duplicate re-mark | IMPLEMENTED |
| L9 | `tests/domain/test_hub_replicator.py::test_the_disconnected_backoff_climbs_from_base_to_cap` — the delay sequence matches the 2s→120s curve | IMPLEMENTED |
| L10 | `tests/domain/test_hub_replicator.py::test_the_disconnected_backoff_resets_on_a_clean_send_not_on_dial_success` | IMPLEMENTED |
| L11 | (model-only; fidelity control (a), reproduced in `docs/display_linkage.tex` §Fidelity against a scratch variant, not a committed file) | MODEL-CHECKED |
| L12 | `tests/test_client_registry.py::test_wait_for_reconnect_wakes_promptly_on_a_concurrent_connect` and `::test_a_reconnect_landing_in_the_get_to_wait_gap_is_not_lost` (PR-465: the generation-counter race close) | IMPLEMENTED |
| L13 | `tests/test_client_registry.py::test_a_wait_snapshotted_after_its_own_connect_waits_out_its_own_timeout` | IMPLEMENTED |
| L14 | (model-only; fidelity control (b), reproduced in `docs/display_linkage.tex` §Fidelity against a scratch variant, not a committed file) | MODEL-CHECKED |
| L15 | `tests/test_client_registry.py::test_wait_for_reconnect_does_not_hold_the_registry_lock` — a concurrent `.get()` from another thread completes while the wait is in flight | IMPLEMENTED |
| L16 | (model-only; bonus fidelity control (c), reproduced in `docs/display_linkage.tex` §Fidelity against a scratch variant, not a committed file) | MODEL-CHECKED |
| L17 | `tests/domain/test_hub_replicator.py::test_a_dial_failure_drives_the_disconnected_branch_not_the_wedged_backoff` — `_back_off()` (the wedge-backoff sleep) is never invoked on the `disconnected` path | IMPLEMENTED |
| L18 | `tests/domain/test_hub_replicator.py::test_a_wedged_display_is_reaped_respawned_and_repainted` et al. (wedge curve), contrasted with L9's disconnected curve — the wedge tests never touch `_disconnected_retry` | IMPLEMENTED |
| L19 | `tests/domain/test_hub_replicator.py` — L9 and L18's tests run in the same module without cross-contamination (shared file, independent `HubReplicator` instances per test) | IMPLEMENTED |
| L20 | `tests/test_client_registry.py::TestConnectAndReconcile` — the reconcile hook lives entirely in `ClientRegistry.get()`, so it fires identically for `DisplayLiveness`'s and `HubReplicator`'s calls; no per-caller branch exists to test separately | IMPLEMENTED |
| L21 | `tests/test_liveness.py::TestDisconnectedPacing::test_interval_relaxes_after_a_failure_and_snaps_back_on_reconnect` | IMPLEMENTED |
| L22 | No dedicated covering test. `DisplayLiveness` and `HubReplicator` share one production `ClientRegistry`/`_lock`, but no test exercises both workers concurrently against one fake to assert the prober's `.get()` is never gated by the replicator's `rwaitdisc` phase. Gap, not a false-covered row. | GAP |
| L23 | `tests/test_hub_never_spawns_display.py::test_no_hub_module_references_the_display_service_lifecycle` — grep-provable, asserts no `src/punt_lux/domain/hub/` file references `ServiceManager`/`DISPLAY_SPEC`/`DisplayServiceManager` | IMPLEMENTED |

Three partitions (L11, L14, L16) have no code to test yet by construction —
they are properties of the *model*, exercised against scratch buggy variants
of `docs/display_linkage.tex` during this mission and reported in its
§Fidelity section, never committed as separate files (following
`docs/hub_replicator.tex`'s own precedent of describing its fidelity variants
in prose rather than as standing artifacts). They become real regression
tests only if the implementation mission chooses to encode the *design*
defects directly (e.g., a test that temporarily monkeypatches
`_CycleOutcome` back to a boolean and asserts the double-sleep reappears) —
not required, since the model-check already proves the corrected design
closes them structurally.

## Merge-critical partitions

The partitions an implementation must not ship without, mirroring
`docs/hub_replicator_coverage.md`'s own §3:

- **L6 — telling `disconnected` from `recovered`.** This is the entire
  reason `_CycleOutcome` becomes a three-way `Literal` (§6.1). Without it,
  the double-sleep defect this design fixes reappears verbatim.
- **L9 — the disconnected backoff reaches its own cap.** The model's I4;
  the fidelity control (L11) shows exactly what regresses if this is
  collapsed onto the wedge backoff.
- **L12 / L15 — the interruptible wait, and its lock-freedom.** The
  model's I6 and I8. L14's fidelity control shows a blocking sleep defeats
  promptness even with everything else correct; L16's shows holding the
  lock during the wait defeats it by a different, equally real path.
- **L17 / L18 — the two backoffs never advance together.** The model's I7;
  structurally guaranteed by disjoint operation frames in the spec, and
  must be structurally guaranteed the same way in the implementation (no
  shared counter, no branch that touches both).
- **L23 — the grep check itself.** The one invariant (I5) that is as much
  a property of the source tree as of any running state; the model proves
  it holds of every *modeled* operation, but only the grep confirms it of
  the *actual* code, forever, including code added after this mission
  closes.

## Implementer notes carried from evaluation

Two points the model cannot enforce, so the implementation must get right
on its own — both are stated in full in `docs/display_linkage.tex`'s Scope
paragraph, restated here as coverage obligations rather than left only in
prose:

- **The disconnected-backoff reset point (L10).** This model resets
  `discBackoff` at `RDialOk` (dial success), because dial and send are one
  atomic step here. Design §6.3 resets `_disconnected_backoff` at a
  *clean send*, one step later. No invariant is sensitive to the
  difference — under sustained disconnection `RDialOk` never fires — but
  L10's covering test (`HubReplicator` disconnected curve, "assert a
  subsequent successful `get()` resets it") must assert the reset follows
  a **successful send**, not merely a successful dial, or it will pass
  against an implementation that resets one step too early.
- **The `wait()`/`.clear()` lost-wakeup window — closed, not merely bounded.**
  `RWaitWoken` and `RWaitTimeout` each model
  `woke = self._reconnected.wait(timeout); self._reconnected.clear(); return woke`
  as one atomic step. The original `Event`-based implementation (both its
  sticky-set and its later clear-before-wait forms) only approximated that
  atomicity, leaving a real window where a concurrent reconnect landing
  between the check and the park could be missed — reported by Bugbot/Copilot
  on PR #465. The fix replaces the `Event` with a monotonic `_reconnect_gen`
  counter plus a `threading.Condition` wrapping `ClientRegistry._lock`:
  `get()` bumps the generation and calls `notify_all()` under the same lock
  `wait_for_reconnect`'s check-then-`Condition.wait_for` runs under, so the
  check ("did a reconnect already land past my snapshot?") and the park
  ("wake me when one does") are genuinely one atomic step — the real
  mechanism now MATCHES the model's abstraction instead of only
  approximating it, so `docs/display_linkage.tex` needs no change. L12's
  `test_a_reconnect_landing_in_the_get_to_wait_gap_is_not_lost` asserts the
  exact race is closed: a reconnect landing in that window returns promptly,
  not after the full backoff.
