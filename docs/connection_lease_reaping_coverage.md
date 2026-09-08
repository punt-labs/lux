# Connection-Lease Reaping: Test-Partition Coverage Audit

Companion to `docs/connection_lease_reaping.tex`, following the same format
as `docs/frame_expiry_coverage.md` and
`docs/hub_display_reconciliation.tex`'s own "Test Partitions" section. This
is a **modeling-mission** artifact (bead `lux-d84d`): the partitions below
are the contract the implementation mission (`rmh`) builds against and the
partitions its tests must cover — each names the behaviour a test must
exercise, and the "Expected covering test" column names where that test
belongs, not a test that exists today. When the implementation mission
lands, replace each placeholder with the real test name; a partition left
unchecked at that point is a gap, not a missing row in this table.

## Round 2: why this table changed

Round 1 of this audit was written against a model that collapsed every
departure into one atomic `Reap`. The implementation built from that model
passed 4,730 tests and an independent re-verification, and a four-way review
still found three ownership-integrity holes — because the model had only one
departure shape to test against, and the code has three. This round adds the
partitions that name each hole explicitly (self-reap-on-write,
graceful-departure-releases, read-is-non-destructive, write-renews-lease)
and revises every partition whose underlying operation changed shape
(`Reap` is gone; `Read`, `Depart`, and `Claim` replace it).

## Round 2 addendum: TimedReap, and the gap below is now closed

The first cut of round 2 made every departure pull-based: discharged only by
`Depart`'s external signal or `Claim`'s embedded sweep of others. The design
gap that section originally surfaced — "a connection with neither signal has
no operation in the refined model that reaps it" — turned out to be the
reported bug itself, not a residual edge case: the bead's own evidence is a
connection that persisted 25.79 hours with the 30-second lease never firing,
because nothing pull-based ever ran for it. The leader ruled the earlier
"reads and writes are the only triggers" decision reversed on this evidence
and added `TimedReap`: the identical atomic deregister-and-release predicate
`Depart` performs, guarded only on `lease~c? = llapsed` — no read, no other
connection's write, and no detected disconnect is a precondition of it
firing. I1 is strengthened accordingly, from "reaped, assuming something
eventually triggers it" to unconditional. The design-gap writeup immediately
below is retained rather than deleted, because the mechanism it correctly
diagnosed (pull-based reaping cannot promise a bound independent of other
parties' activity) is exactly what the ruling was made from; a superseding
note follows it rather than erasing it.

## Spec-operation → design-element mapping

The design is the fix `docs/connection_lease_reaping.tex`'s `Read`,
`Depart`, and `Claim` schemas specify, realized against the current code at
`src/punt_lux/domain/hub/hub_clients.py` (`HubClientRegistry`),
`client_session.py` (`ClientSession`), `session_lease.py` (`SessionLease`),
`owner_tracker.py` (`OwnerTracker`), `owner.py` (`Owner`),
`hub_display.py` (`HubDisplay.drop_connection`, `HubDisplay.apply`,
`HubDisplay._reap_and_release`), `lifecycle.py` (`disconnect_connection`),
and `session_cleanup.py` (the MCP session teardown leg both the graceful
disconnect and the SDK's idle-reap take).

| Spec operation | Design element |
|---|---|
| `Connect` | `HubDisplay.identify_client` / `register_client` → `HubClientRegistry.record(connection_id, identity)` — upsert semantics, "any contact is a renewal" |
| `Renew` | `HubClientRegistry.record(connection_id)` with no identity argument — an explicit `identify`/`register_client` call that is not itself a write |
| `TransportDies` | Not a Hub-observable event of its own for a client-registry connection — see the residual design gap below |
| `LeaseLapse` | `SessionLease.is_live` returning `False` for *any* registered session, discovered lazily; no longer gated on a dead transport in this round (§ "What changed" below) |
| `Read` (**fixed**) | `HubClientRegistry.named_sessions`/`live_sessions`/`repos`, made non-destructive: filters to the live set without mutating `_sessions`. Does not exist as a mutating operation yet — this is the change the implementation mission must make |
| `Read` (**H1-buggy**, i.e. current code) | `HubClientRegistry.named_sessions`'s `_sweep_locked` call, whose six callers (`HubReads.client_sessions`, `CallbackMenu.from_named`, `client_details.py`, `callback_hold.py`, and the rest) discard the swept set instead of releasing it |
| `Depart` (**fixed**) | `HubDisplay.drop_connection`, changed to release: atomically discard the session **and** call `OwnerTracker.release_all(connection_id)` (or equivalent) in the same step, for both the graceful-disconnect and the SDK idle-reap triggers, which both route through `session_cleanup.py` → `lifecycle.disconnect_connection` → `HubDisplay.drop_connection` today |
| `Depart` (**H2-buggy**, i.e. current code) | `HubDisplay.drop_connection` exactly as shipped: `self._clients.discard(connection_id)`, ownership untouched — this is the behaviour `connection_lease_reaping_no_release_buggy.tex` now models (retargeted from round 1's lease-lapse framing) |
| `Claim` (**fixed**) | `HubDisplay.apply`, changed to (1) renew the caller's own lease first, (2) then sweep every *other* lapsed connection via `HubClientRegistry.reap`-equivalent and release what each owned, (3) then perform the existing `SetProperty`/`RemoveElement`/`AddElement` ownership check against the result |
| `Claim` (**H3-buggy**, i.e. current code) | `HubDisplay.apply` exactly as shipped: calls `self._reap_and_release()` — an unconditional sweep of every lapsed session including the caller's own — before doing anything else, and never calls anything that renews the caller |
| `TimedReap` (**new, round 2 addendum**) | Does not exist yet in any form. Must be built: a periodic background task (interval no longer than the shortest `SessionLease` TTL in use, `SessionLease._TTL_BY_KIND`'s `cli` at 90s today) that calls the same release path `HubDisplay._reap_and_release` already has, for every session `HubClientRegistry` reports as lapsed, independent of any read or write ever occurring |

## A design gap this model surfaced — now resolved by the round-2 ruling

**Superseded by the addendum above; retained for the record.** The
diagnosis below was correct and is exactly what produced the ruling that
added `TimedReap`. It no longer describes an open gap.

The operator's ruling settles the *shape* of the fix: one coordinator, one
atomic step, reads non-destructive, writes renewing. It does not settle
*how often* that coordinator's lapse-triggered path actually runs, and this
round's refinement sharpens rather than closes the gap round 1 first
surfaced:

1. **The lapse-triggered path is now write-embedded, not periodic or
   read-triggered.** Round 1 assumed the fix would live in the read path
   (a sweep triggered by "who's live" reads, corrected to also release).
   The ruling instead moves reads to non-destructive and puts the only
   concrete lapse-driven release inside `Claim`/`apply` — `Depart`'s trigger
   (a real disconnect or the SDK's idle-reap) is independent of lease state
   entirely. A connection with **neither** a graceful-disconnect signal (a
   killed process, no clean shutdown — e.g. `SIGKILL`) **nor** any live peer
   ever calling `apply` again has no operation in the refined model that
   reaps it. `LeaseLapse` can still fire on it (that state fact is not
   lost), but nothing consumes the fact into a release.
2. **This is the same gap round 1 named, now with a concrete answer for
   who is NOT covered.** Round 1 said "the fix has to work correctly on a
   lazy sweep... a stale connection's ownership is never released because
   the sweep that would release it never runs." The ruling's `Claim`-
   embedded sweep answers "released when?" for the common case (some other
   client keeps drawing), and `Depart` answers it for any client kind with
   an explicit disconnect signal (an MCP session end, an SDK idle-reap).
   Neither answers it for a killed connection on an otherwise-idle Hub.
3. **Resolved (round 2 addendum).** The leader ruled on exactly this
   evidence: a purely pull-based design cannot promise the bead's own
   premise, so the lease needed a real, periodic backstop. `TimedReap`
   (Section~\ref{sec:timedreap} of `docs/connection_lease_reaping.tex`) is
   that backstop — the identical release predicate, guarded only on
   `lease~c? = llapsed`, with no read, write, or disconnect signal as a
   precondition. I1 is now unconditional. The implementation mission's
   task is no longer "decide whether to add a periodic sweep" but "build
   the one this model specifies," at an interval no longer than the
   shortest `SessionLease` TTL in use (partition TR1, below).

## Operation partitions and their tests

| Partition | Meaning | Expected covering test |
|---|---|---|
| C1 | a fresh `Connect` registers a new connection with a live lease and no owned scenes | `test_hub_clients.py::test_a_fresh_connect_registers_with_a_live_lease` |
| C2 | `Connect` on an already-registered connection is a renewal, not a second session (I4: no ownership touched) | `test_hub_clients.py::test_a_repeat_connect_renews_rather_than_duplicates` |
| C3 | `Connect` under an identity another, still-live connection already holds does not evict, preempt, or touch the other's ownership (I4) | `test_hub_clients.py::test_a_second_live_connect_under_one_identity_does_not_preempt` |
| R1 | an explicit, non-write contact (`identify`/`register_client`) renews the lease while the transport is alive | `test_client_session.py::test_renewed_extends_the_lease` |
| **RD1 (read-is-non-destructive)** | `named_sessions`/`live_sessions`/`repos` never remove a lapsed session from the registry, however long it has been called after the lease lapsed — the registry entry, and the ownership it carries, are still there on the *next* call, live or lapsed | `test_hub_clients.py::test_live_sessions_never_removes_a_lapsed_session` — the direct regression test for H1 |
| **RD2** | reading through a lapsed connection any number of times, with no intervening `Depart` or `Claim` by any connection, never changes `owner` | `test_hub_display_ownership.py::test_repeated_reads_of_a_lapsed_connection_never_release_its_scenes` |
| **GD1 (graceful-departure-releases)** | `drop_connection` on a connection with a **live** transport and an **unlapsed** lease (an ordinary clean MCP session end, not a timeout) atomically deregisters it **and** releases every scene it owned in the same step | `test_hub_display_ownership.py::test_a_graceful_disconnect_releases_the_departing_connections_scenes` — the direct regression test for H2 |
| GD2 | `drop_connection` on a connection that owns no scenes is a no-op on `owner` | `test_hub_display_ownership.py::test_a_graceful_disconnect_of_an_ownerless_connection_touches_no_scene` |
| GD3 | the SDK's idle-reap path (`session_cleanup.py`'s teardown leg) produces the identical release as an explicit client disconnect — one coordinator, two triggers | `test_session_cleanup.py::test_idle_reap_releases_ownership_identically_to_a_graceful_disconnect` |
| **WR1 (write-renews-lease)** | a successful `apply` call renews the calling connection's own lease, whether or not that lease had already lapsed at the moment of the call | `test_hub_display_ownership.py::test_apply_renews_the_calling_connections_own_lease` |
| **SR1 (self-reap-on-write, the H3 regression)** | a connection whose lease has lapsed under a transport that never died still succeeds at its own next `apply` call, keeps its registration, and keeps every scene it owned — it is never swept by its own write | `test_hub_display_ownership.py::test_a_connection_with_a_lapsed_lease_survives_its_own_next_apply` — the direct regression test for H3 |
| SR2 | interleaving one connection's repeated `apply` calls with a second connection's `apply` calls (which each also sweep lapsed others) never reaps the first as long as the first's own calls keep renewing it | `test_hub_display_ownership.py::test_interleaved_writers_never_reap_each_other_while_both_stay_live` |
| SR3 | `apply`'s embedded sweep *does* release a genuinely different, lapsed connection's scenes as a side effect of some other connection's write — the sweep-of-others mechanism itself, isolated from the self-exclusion SR1 tests | `test_hub_display_ownership.py::test_apply_releases_a_different_lapsed_connections_scenes_as_a_side_effect` |
| **TR1 (timed-reap-on-idle, the round-2 regression)** | kill the connection's transport, wait one lease interval, and do *nothing else* — no read, no other connection's write, no explicit disconnect — the connection is still, eventually, dropped from the live set **and** every scene it owned becomes unowned. This is the clean run-and-prove the implementation exercises: no other client, no poll, no introspection call, just the timer | `test_hub_display_ownership.py::test_a_killed_connection_is_reaped_by_the_timer_alone_on_an_idle_hub` — the direct regression test for the bead itself (25.79h persistence with the 30s lease never firing) |
| TR2 | `TimedReap` and `Depart` firing on the same connection at the same instant (a race between the background timer and an arriving disconnect signal) leave the registry and ownership table in the identical state either order runs — same predicate, same postcondition | `test_hub_display_ownership.py::test_timed_reap_racing_a_graceful_disconnect_converges` |
| TR3 | `TimedReap` on a connection that owns no scenes is a no-op on `owner`, same as `Depart` and `Claim`'s embedded sweep | `test_hub_display_ownership.py::test_timed_reap_of_an_ownerless_connection_touches_no_scene` |
| TR4 | `TimedReap` never fires on a connection whose lease is still live, however long the timer has been running — the periodic check is a filter, not an unconditional sweep | `test_hub_clients.py::test_timed_reap_never_touches_a_connection_with_a_live_lease` |
| KT1 (kill-transport-then-depart) | a connection whose transport has died, once disconnected (gracefully or via the SDK's idle-reap) is dropped from the live set **and** every scene it owned becomes unowned in the same step | `test_hub_display_ownership.py::test_depart_of_a_dead_transport_connection_releases_its_scenes` |
| KT2 | a connection making continuous, renewing contact (`Renew` or `Claim`) is never a candidate for `LeaseLapse`, however long it has been actively used | `test_session_lease.py::test_continuous_renewal_prevents_lease_lapse` |
| KT3 | departing (gracefully or by lapse) a connection that owns *no* scenes is a no-op on `owner` | `test_hub_display_ownership.py::test_departing_an_ownerless_connection_touches_no_scene` |
| RB1 (reconnect-before-departure) | a new connection under the same identity connects while the old one is still registered — the new connection can `Claim` any scene the old one does not own, but is blocked from a scene the old one still owns until the old one actually departs | `test_hub_display_ownership.py::test_a_reconnect_before_departure_is_blocked_from_the_predecessors_scene` |
| RD3 (reconnect-during-departure) | a new connection's `Connect` interleaved with the old connection's `LeaseLapse`/departure in either order produces the same end state: the new connection ends up live, the old one departed, ownership released | `test_hub_display_ownership.py::test_reconnect_interleaved_with_departure_is_order_independent` |
| RA1 (reconnect-after-departure) | a new connection that connects only once the old one has already fully departed can immediately `Claim` the scene the old one used to own | `test_hub_display_ownership.py::test_a_reconnect_after_departure_claims_the_released_scene` — the positive-outcome trace in the spec's Verification section |
| MI1 (multiple identities) | two connections of *different* identities, one departed and one live, never interact: the live one's `Claim`s are never blocked by the other's ownership | `test_hub_display_ownership.py::test_departing_one_identitys_connection_never_blocks_an_unrelated_identity` |
| CL1 | `Claim` on an unowned scene succeeds unconditionally for any live connection (the `AddElement`-onto-fresh-scene case) | `test_owner_tracker.py::test_claiming_an_unowned_scene_always_succeeds` |
| CL2 | `Claim` on a scene the caller already owns is idempotent | `test_owner_tracker.py::test_reclaiming_ones_own_scene_is_idempotent` |
| CL3 | `Claim` on a scene owned by a *different, still-live* connection is refused (`HubOwnershipError`), independent of this bead's fix — existing, correct behaviour the fix must not weaken | `test_owner_tracker.py::test_claiming_another_live_connections_scene_raises` |

Partitions in **bold** are new or substantially reframed in this round; they
are the direct coverage requirement for H1 (RD1, RD2), H2 (GD1, GD3), H3
(WR1, SR1, SR2, SR3), and the addendum's own regression, TR1 (the bead's
own reported scenario: kill, wait, and touch nothing else). A test suite
covering only the round-1 partitions (`KT1`–`RA1` under their old
`Reap`-based names) would have looked complete and still missed all three
holes — this is precisely what happened. A suite covering H1/H2/H3 but not
TR1 would look complete a second time and still miss the bead itself, since
none of H1/H2/H3 exercises an otherwise-idle Hub.

Trace lengths quoted below (and in `docs/connection_lease_reaping.tex`'s
own Fidelity section) are illustrative witnesses from a specific run, not a
guaranteed reproducible artifact: ProB's search order is not obliged to
return the same trace on every invocation, and the shortest available
witness sometimes differs run to run once more than one operation is
enabled at the same state (`Depart` and `TimedReap` are the clearest
case — see the unconditional-I1 discussion in the main spec's Verification
section). The `FOUND`/`NOT found` verdict itself is deterministic and is
what the gate actually checks.

## The invariants, and how they are checked

- **I1** — transport-gone implies *unconditionally* eventually reaped.
  Strengthened in this round's addendum. Checked by reachability of the
  positive outcome (`TransportDies`;`Depart` or `TransportDies`;
  `LeaseLapse`;`TimedReap` both complete — `probcli` goal `FOUND`,
  confirmed at `DEFAULT_SETSIZE 1`, `2`, and `3`) and, for the
  *unconditional* half specifically, by inspection: `TimedReap`'s guard —
  `c? \in registered \land lease~c? = llapsed` — mentions no other
  connection and no read, so it is satisfiable by a periodic caller with
  no external signal at all. Confirmed even with `CONN` bounded to a
  single element (`DEFAULT_SETSIZE 1`), which rules out any second
  connection appearing in the model at all.
- **I2** — reap releases ownership. Checked by reachability of the
  negation: `NOT found` against the fixed spec at `DEFAULT_SETSIZE 2`
  (1,233 states, 9 operations covered including `TimedReap`) and `3`
  (313,093 states, no deadlock).
- **I3** — at most one live owner per identity. Checked the same way:
  `NOT found` against the fixed spec, `FOUND` against
  `connection_lease_reaping_no_release_buggy.tex` (5-step trace).
- **I4** — reconnect inherits nothing special (settled). Checked
  structurally: `Connect`'s definition is unchanged from round 1 and never
  reads `owner` or another connection's `identity`.
- **I5** — leaving the registry iff released, however triggered. Checked
  in two parts: the same reachability goal as I2 (`NOT found` against the
  fixed spec; `FOUND` against all three controls) plus the structural fact
  that `Read` is `\Xi ConnReg` and so cannot change `registered` by
  construction. `TimedReap` is the fourth removal path this round adds to
  the proof — its predicate is `Depart`'s verbatim with one added guard
  conjunct, so it needs no separate argument beyond the one `Depart`
  already has.
- **I6** — a live writer keeps its ownership. Checked by reachability of a
  goal that adds `transport(c) = tup` to I5's formula: `NOT found` against
  the fixed spec; `FOUND` against `connection_lease_reaping_self_reap
  _buggy.tex` (a minimal witness through `Connect`;`LeaseLapse`;`Claim`
  alone, never calling `TransportDies`, `Depart`, or `TimedReap`).
- **Deadlock-freedom and no cross-operation race.** `Connect` carries no
  guard, so it is enabled in every reachable state of the fixed spec and
  all three controls; full `-model_check` over `DEFAULT_SETSIZE 2` and `3`
  reports no deadlock and full operation coverage (9 operations) for the
  fixed spec, unchanged after `TimedReap`'s addition. Because
  `TimedReap`, `Depart`, and `Claim`'s embedded sweep compute the same
  postcondition wherever more than one is simultaneously enabled on the
  same connection, the model has no reachable state in which their
  effects could conflict — whichever fires first disables the others'
  guard on that connection (`c? \in registered` fails once any one of
  them has removed it), which the full model-check's absence of any
  invariant violation or deadlock confirms rather than merely assumes.

Re-run `fuzz` and the `probcli` goal checks in
`docs/connection_lease_reaping.tex`'s Verification section, and the
per-hole checks in its Fidelity section, whenever `hub_clients.py`,
`client_session.py`, `session_lease.py`, `owner_tracker.py`, `owner.py`,
`hub_display.py`'s `drop_connection`/`apply`/`_reap_and_release`,
`lifecycle.py`'s `disconnect_connection`, or `session_cleanup.py` change.
