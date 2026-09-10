# Display Linkage: Test-Partition Coverage Audit

Companion to `docs/display_linkage.tex`, following the same format as
`docs/hub_replicator_coverage.md` and `docs/connection_lease_reaping_coverage.md`.
This is a **design-phase** artifact: `docs/architecture/display-presence-demand-driven.md`
is ratified but unimplemented (bead `lux-81t3.1`), so every "Expected covering
test" below names where a test belongs — the exact bullet in the design
document's own §10 item 11 ("Tests") that the implementation mission must
satisfy — not a test that exists today. When the implementation mission
lands, replace each placeholder with the real test name; a partition left
unchecked at that point is a gap, not a missing row in this table.

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
| `RDialFail` | `ClientRegistry.get()` raising `RuntimeError` — the new `disconnected` arm of `_CycleOutcome` (§6.1), routed through `HubReplicator._wait_disconnected` (§6.3) |
| `RWaitWoken` | `ClientRegistry.wait_for_reconnect(timeout)` returning `True` |
| `RWaitTimeout` | `ClientRegistry.wait_for_reconnect(timeout)` returning `False` |
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
| L1 | `DisplayLinkage.classify` truth table (4 branches, no fakes) | PLANNED |
| L2 | `DisplayLinkage.classify` truth table (4 branches, no fakes) | PLANNED |
| L3 | `DisplayLinkage.classify` truth table (4 branches, no fakes) | PLANNED |
| L4 | `DisplayLinkage.classify` truth table (4 branches, no fakes) | PLANNED |
| L5 | `DisplayLinkage.classify` truth table (4 branches, no fakes) | PLANNED |
| L6 | `_CycleOutcome`/`_run_cycle` — a fake `ClientProvider` whose `get()` raises `RuntimeError` drives the `disconnected` branch; assert `_back_off()` is never invoked | PLANNED |
| L7 | `DisplayLinkOperations.get_link()` with a fake `ClientRegistry` reporting a fresh connect, plus `test_recovery`-style reconcile coverage inherited from DES-068 | PLANNED |
| L8 | `_CycleOutcome`/`_run_cycle` — a fake `ClientProvider` whose `get()` succeeds while already connected; assert no duplicate re-mark | PLANNED |
| L9 | `HubReplicator` disconnected curve — assert the delay sequence matches the 2s→120s curve across repeated cycles | PLANNED |
| L10 | `HubReplicator` disconnected curve — assert a subsequent successful `get()` resets it | PLANNED |
| L11 | (model-only; fidelity control (a), reproduced in `docs/display_linkage.tex` §Fidelity against a scratch variant, not a committed file) | MODEL-CHECKED |
| L12 | `ClientRegistry.wait_for_reconnect` — a thread sets `_reconnected` while another is blocked in `wait_for_reconnect(60.0)`; assert the waiter returns `True` in well under a second | PLANNED |
| L13 | `ClientRegistry.wait_for_reconnect` — a call with nothing setting the event returns `False` once its timeout elapses | PLANNED |
| L14 | (model-only; fidelity control (b), reproduced in `docs/display_linkage.tex` §Fidelity against a scratch variant, not a committed file) | MODEL-CHECKED |
| L15 | `ClientRegistry.wait_for_reconnect` — a second test asserts `wait_for_reconnect` does not hold `self._lock` for its duration (a concurrent `.get()` from another thread completes while the wait is in flight) | PLANNED |
| L16 | (model-only; bonus fidelity control (c), reproduced in `docs/display_linkage.tex` §Fidelity against a scratch variant, not a committed file) | MODEL-CHECKED |
| L17 | `_CycleOutcome`/`_run_cycle` — assert `_back_off()` (the wedge-backoff sleep) is never invoked on the `disconnected` path — the specific double-sleep regression review found | PLANNED |
| L18 | `HubReplicator` disconnected curve, contrasted with the existing wedge-backoff tests in `test_hub_replicator.py` (`test_a_wedged_display_is_reaped_respawned_and_repainted` et al.) | PLANNED |
| L19 | Combination of L9/L18 — both curves exercised in the same test session without cross-contamination | PLANNED |
| L20 | `DisplayLiveness` — with a fake `KeepaliveClients`, assert a successful probe after a disconnection is indistinguishable in effect from the replicator's own reconnect (reconcile fires) | PLANNED |
| L21 | `DisplayLiveness` — with a fake `KeepaliveClients` whose `get()` always raises `RuntimeError`, assert the loop's wait interval becomes `_DISCONNECTED_PROBE_INTERVAL` after the first failure, and reverts to `_interval` on recovery | PLANNED |
| L22 | `DisplayLiveness` — exercised concurrently with `HubReplicator` against one fake `ClientRegistry`; assert the prober's own `.get()` is never gated by the replicator's phase | PLANNED |
| L23 | Grep-provable safety check (§12 invariant 5): a test (or a `make check`-wired grep) asserting no source file under `src/punt_lux/domain/hub/` references `ServiceManager` in connection with `DISPLAY_SPEC`/`DisplayServiceManager` | PLANNED |

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
- **The `wait()`/`.clear()` lost-wakeup window.** `RWaitWoken` and
  `RWaitTimeout` each model
  `woke = self._reconnected.wait(timeout); self._reconnected.clear(); return woke`
  as one atomic step. The real two-statement body has a window in which a
  second `.set()` landing between the wake and the `.clear()` is silently
  discarded — out of this model's scope by construction, not oversight.
  The consequence is bounded (added retry latency via the next dial, never
  lost content or a stuck wait, since I4 already proves the retry delay
  itself is capped), but L12/L15's covering tests
  (`ClientRegistry.wait_for_reconnect`) should include a case that lands a
  second `.set()` in that exact window and asserts the bounded-latency
  degradation, not a hang.
