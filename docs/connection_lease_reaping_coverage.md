# Connection-Lease Reaping: Test-Partition Coverage Audit

Companion to `docs/connection_lease_reaping.tex`, following the same format
as `docs/frame_expiry_coverage.md` and
`docs/hub_display_reconciliation.tex`'s own "Test Partitions" section. This
is a **modeling-mission** artifact (bead `lux-d84d`): no code fix exists yet.
The partitions below are the contract the implementation mission builds
against — each names the behaviour a test must exercise, and the "Expected
covering test" column names where that test belongs, not a test that exists
today. When the implementation mission lands, replace each placeholder with
the real test name; a partition left unchecked at that point is a gap, not a
missing row in this table.

## Spec-operation → design-element mapping

The design is the fix implied by `docs/connection_lease_reaping.tex`'s
`Reap` schema, realized against the current code at
`src/punt_lux/domain/hub/hub_clients.py` (`HubClientRegistry`),
`client_session.py` (`ClientSession`), `session_lease.py` (`SessionLease`),
`owner_tracker.py` (`OwnerTracker`), `owner.py` (`Owner`), and
`hub_display.py` (`HubDisplay.drop_connection`, `HubDisplay.apply`) /
`lifecycle.py` (`disconnect_connection`).

| Spec operation | Design element |
|---|---|
| `Connect` | `HubDisplay.identify_client` / `register_client` → `HubClientRegistry.record(connection_id, identity)` — upsert semantics, "any contact is a renewal" |
| `Renew` | `HubClientRegistry.record(connection_id)` with no identity argument — any authenticated contact renews the existing session's lease |
| `TransportDies` | Not currently a Hub-observable event of its own for a client-registry connection (see the design gap in the Introduction/§ below) — an MCP/REST/WS peer going away today produces no signal beyond the eventual lease lapse; the Hub-Display *socket* leg (`SocketListener`) does get a direct `recv`-failure signal, but that is `docs/hub_display_reconciliation.tex`'s connection, not this one |
| `LeaseLapse` | `SessionLease.is_live` returning `False`, discovered lazily the next time `HubClientRegistry.named_sessions`/`live_sessions` runs |
| `Reap` (**fixed**) | Does not exist yet. Must be built: `HubClientRegistry.named_sessions`'s sweep needs to report which connection ids it just dropped, and something with access to `OwnerTracker` — `HubDisplay`, which already owns both `_clients` and `_owners` — needs to call `elements_owned_by(connection_id)` and release them for every id the sweep reports |
| `Reap` (**buggy**, i.e. current code) | `HubClientRegistry.named_sessions`'s sweep (drops the session, no callback) composed with `HubDisplay.drop_connection` (drops client registration only, explicitly leaves scenes "owned by its id") |
| `Claim` | `HubDisplay.apply`'s `SetProperty`/`RemoveElement` arm, gated by `OwnerTracker.require_ownership`; and (folded into the same schema for this model) `AddElement`'s `Owner.from_session` grant when the target scene has no existing owner |

## A design gap this model surfaces (not settled by the operator ruling)

The operator's ruling settles *that* the lease is the reaping mechanism and
*that* reconnect does nothing special (I4). It does not settle *how* reap
gets wired to ownership release, and the current code has no such wiring at
all, in either direction a fix might take:

1. **The sweep is pull-based, not a background timer.** `named_sessions`
   only runs when something calls `live_sessions`/`named_sessions` —
   `HubReads.client_sessions` (introspection), `CallbackMenu.from_named`
   (menu composition), `client_details.py`, `callback_hold.py`. There is no
   periodic sweep independent of some caller asking "who's live." A fix
   that assumes a background tick (as `frame_expiry.tex`'s `ExpirySweep`
   has for frame TTLs) does not match this code; the fix has to work
   correctly on a *lazy* sweep, including the case where nobody calls
   `live_sessions` for a long time and a stale connection's ownership
   is never released because the sweep that would release it never runs.
2. **`HubClientRegistry` and `OwnerTracker` do not know about each other.**
   `HubClientRegistry.named_sessions`'s sweep silently drops rows from its
   own `_sessions` dict; it has no reference to `OwnerTracker` and calls
   nothing when it reaps. `HubDisplay` is the only object holding both
   (`self._clients` and `self._owners`), so the natural fix point is
   `HubDisplay` reacting to the *result* of a sweep, not the sweep
   reaching into a collaborator it currently has no reference to.

**Recommendation for the implementation mission:** change
`HubClientRegistry.named_sessions`'s return type (or add a companion method)
to report the *newly reaped* connection ids for that call — not just the
survivors — and have `HubDisplay` (which already composes both registries)
call `self._owners.keys_for(id)` and release them for each one, every time
it reads through `HubClientRegistry`. This keeps the release synchronous
with the only signal the code currently has (a lazy sweep triggered by some
reader), rather than inventing a background timer the code does not have
today. This recommendation is the leader's decision to ratify or amend, not
something this model has authority to settle on its own.

## Operation partitions and their tests

| Partition | Meaning | Expected covering test |
|---|---|---|
| C1 | a fresh `Connect` registers a new connection with a live lease and no owned scenes | `test_hub_clients.py::test_a_fresh_connect_registers_with_a_live_lease` |
| C2 | `Connect` on an already-registered connection is a renewal, not a second session (I4: no ownership touched) | `test_hub_clients.py::test_a_repeat_connect_renews_rather_than_duplicates` |
| C3 | `Connect` under an identity another, still-live connection already holds does not evict, preempt, or touch the other's ownership (I4) | `test_hub_clients.py::test_a_second_live_connect_under_one_identity_does_not_preempt` |
| R1 | contact renews the lease while the transport is alive | `test_client_session.py::test_renewed_extends_the_lease` |
| KT1 (**kill-transport-then-reap**) | a connection whose transport has died, once its lease lapses, is dropped from the live set **and** every scene it owned becomes unowned in the same step | `test_hub_display_ownership.py::test_reap_of_a_dead_connection_releases_its_scenes` — the core regression test for this bead |
| KT2 | a connection with an *alive* transport is never reaped, however long it has been idle in this model (bounded by `Renew` always being available) — the real system still bounds this by TTL, which this model does not need to re-derive since I1 only claims dead-transport reaping is unblocked, not that live connections are ever swept | `test_session_lease.py::test_a_live_transport_connection_never_lapses_under_continuous_contact` |
| KT3 | reaping a connection that owns *no* scenes is a no-op on `owner` (the domain-restricted release is vacuous, not an error) | `test_hub_display_ownership.py::test_reaping_an_ownerless_connection_touches_no_scene` |
| RB1 (**reconnect-before-reap**) | a new connection under the same identity connects while the old one is still registered (transport possibly already dead, lease not yet lapsed) — the new connection can `Claim` any scene the old one does not own, but is blocked from a scene the old one still owns until the old one is actually reaped | `test_hub_display_ownership.py::test_a_reconnect_before_reap_is_blocked_from_the_predecessors_scene` |
| RD1 (**reconnect-during-reap**) | a new connection's `Connect` interleaved with the old connection's `LeaseLapse`/`Reap` in either order produces the same end state: the new connection ends up live, the old one reaped, ownership released — no interleaving-dependent outcome | `test_hub_display_ownership.py::test_reconnect_interleaved_with_reap_is_order_independent` |
| RA1 (**reconnect-after-reap**) | a new connection that connects only once the old one has already been fully reaped can immediately `Claim` the scene the old one used to own | `test_hub_display_ownership.py::test_a_reconnect_after_reap_claims_the_released_scene` — the positive-outcome trace in the spec's Verification section |
| MI1 (**multiple identities**) | two connections of *different* identities, one reaped and one live, never interact: the live one's `Claim`s are never blocked by the other's ownership, and I3's identity comparison genuinely distinguishes them (not merely a coincidence of the model having only one identity) | `test_hub_display_ownership.py::test_reaping_one_identitys_connection_never_blocks_an_unrelated_identity` |
| LR1 (**lease-renewal-keeps-live**) | a connection that keeps making contact (`Renew` on every check, transport never dying) is never a candidate for `LeaseLapse`/`Reap`, however many `Claim`s it accumulates | `test_hub_clients.py::test_continuous_renewal_prevents_lease_lapse` |
| CL1 | `Claim` on an unowned scene succeeds unconditionally for any live connection (the `AddElement`-onto-fresh-scene case) | `test_owner_tracker.py::test_claiming_an_unowned_scene_always_succeeds` |
| CL2 | `Claim` on a scene the caller already owns is idempotent | `test_owner_tracker.py::test_reclaiming_ones_own_scene_is_idempotent` |
| CL3 | `Claim` on a scene owned by a *different, still-live* connection is refused (`HubOwnershipError`), independent of this bead's fix — this is the existing, correct behaviour `require_ownership` already has and the fix must not weaken | `test_owner_tracker.py::test_claiming_another_live_connections_scene_raises` |

## The invariants, and how they are checked

- **I1** — transport-gone implies eventually reaped. Checked structurally
  (`Renew`'s guard forecloses self-renewal once dead; `LeaseLapse`/`Reap`'s
  guards are never additionally blocked) and by reachability: the full
  chain `TransportDies`;`LeaseLapse`;`Reap` is confirmed non-vacuous
  (`probcli` goal `FOUND`, 8-step trace).
- **I2** — reap releases ownership, the damaging property. Checked by
  reachability of the negation: `NOT found` against the committed
  `Reap` (all 76,420 reachable states visited over `DEFAULT_SETSIZE 3`),
  `FOUND` (7-step trace) against `connection_lease_reaping_no_release_buggy.tex`.
- **I3** — at most one live owner per identity. Checked the same way:
  `NOT found` against the fix, `FOUND` (9-step trace) against the buggy
  control.
- **I4** — reconnect inherits nothing special (settled). Checked
  structurally: `Connect`'s definition never reads `owner` or any other
  connection's `identity`, so no successor state can show a reconnect
  transferring ownership; not a reachability check, because there is no
  "transfer" mechanism in the model to reach in the first place.
- **Deadlock-freedom.** `Connect` carries no guard, so it is enabled in
  every reachable state of both the fixed spec and the buggy control;
  full `-model_check` over `DEFAULT_SETSIZE 3` reports no deadlock and
  100% operation coverage for both.

Re-run `fuzz` and the four `probcli` goal checks in
`docs/connection_lease_reaping.tex`'s Verification section whenever
`hub_clients.py`, `client_session.py`, `session_lease.py`,
`owner_tracker.py`, `owner.py`, or `hub_display.py`'s `drop_connection`/
`apply` change.
