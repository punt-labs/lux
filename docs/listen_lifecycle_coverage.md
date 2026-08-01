# Listen-Leg Lifecycle: Test Partitions and Coverage

Derived from [`listen_lifecycle.tex`](listen_lifecycle.tex). Each partition is
one branch of one operation's guard — the cases the model distinguishes, and
therefore the cases the implementation has to get right. The audit column says
what the suite exercises now that the design is implemented; the notes under each
table keep the pre-fix reading, because what was missing is why each test exists.

A model-checked design is not a tested one. The model proves that no
interleaving of the specified operations violates the invariants; the tests
prove that the code implements those operations. Both are needed, and a passing
test that stubs the mechanism is a gap, not coverage.

## Reading the audit

- **covered** — an existing test drives the real objects through this branch.
- **partial** — the branch is reached, but the property the model cares about
  is not asserted.
- **gap** — nothing reaches this branch.

Tests are named without their `test_` prefix. The files that matter are
`tests/test_ws_listen.py`, `tests/test_ws_e2e.py`,
`tests/domain/test_callback_hold.py`, `tests/domain/test_hub_clients.py`,
`tests/domain/test_listener_slot.py`, and
`tests/operations/test_callback_operations.py`. All of them drive real domain
objects — no stubbed router, no mocked registry — so where they cover a branch,
they cover it honestly.

## Connect

| # | Partition | Audit |
|---|-----------|-------|
| C1 | First occupant: attach with the listener slot empty | covered — `the_handshake_readies_the_shared_connection_id` |
| C2 | Attach displacing a **pumping** predecessor (two live sessions of one identity) | covered — `a_second_live_session_of_one_identity_takes_the_connection` |
| C3 | Attach displacing a **suspended** predecessor (the reconnect after backoff) | covered — `a_superseded_sessions_teardown_leaves_its_successor_whole` |
| C4 | Attach clears the previous occupant's callbacks, and the bar is re-pushed when it does | covered — `a_new_leg_arrives_with_none_of_its_predecessors_menu_entries` (asserts the mark), `a_new_leg_starts_with_none_of_its_predecessors_callbacks`, `a_first_leg_clears_nothing_and_says_so`, `a_first_leg_with_no_entries_to_clear_asks_for_no_menu_push`, `taking_the_slot_leaves_the_previous_occupants_callbacks_behind` |
| C5 | Attach renews the lease | covered — attach records identity and lease in the one write `a_declared_ttl_lapses_an_app_session_that_would_be_permanent` drives |

C2 and C3 are the whole point. Neither can be written with one WebSocket
client: the test needs a second connection under the same
`X-Lux-Client-*` headers, opened while the first is still live (C2) or after
the first's socket has gone but before its teardown has run (C3).

## Drop and teardown

| # | Partition | Audit |
|---|-----------|-------|
| T1 | Drop from `sattached` — the handshake write fails | covered — `a_peer_that_dies_before_the_handshake_leaves_no_listener` |
| T2 | Drop from `spumping` — the peer goes away | covered — `a_departed_connections_menu_items_leave_with_it` |
| T3 | Teardown **owned**: this session still holds the slot; listener and callbacks both go | covered — `a_teardown_releases_the_leg_and_its_callbacks_together` asserts both, and `a_peer_that_dies_before_the_handshake_leaves_no_listener` asserts the slot |
| T4 | Teardown **owned**: listener and callbacks go in one critical section | covered — `releasing_the_slot_cannot_leave_the_callbacks_behind` (no such state exists to reach) and `the_leg_and_its_callbacks_are_written_under_one_lock` |
| T5 | Teardown **stale**: a successor holds the slot; the slot and its callbacks are not removed | covered — `a_superseded_sessions_teardown_leaves_its_successor_whole`, `a_teardown_by_a_session_that_lost_the_slot_removes_nothing` |
| T6 | Teardown releases this session's **own** writer and subscriptions on every path | covered — `a_superseded_leg_takes_the_subscriptions_it_made_when_it_goes`, `release_writer_takes_the_departing_legs_subscriptions_only` |
| T7 | A stale teardown leaves the successor's writer and subscriptions alone | covered — `a_stale_teardown_leaves_the_successors_subscriptions_and_writer` publishes on the survivor's topic |
| T8 | The session, its identity, and its lease survive any teardown | covered — `a_departed_connections_menu_items_leave_with_it` asserts the survivor |
| T9 | Teardown after the **lease sweep**: no session at all; the writer and subscriptions still go, and the bar is re-pushed | covered — `a_swept_session_still_has_its_writer_and_subscriptions_released`, `a_teardown_after_the_sweep_says_the_session_itself_is_gone` |

T6 and T9 apply the model's ownership clause to state the model abstracts.
`listen_lifecycle.tex` tracks the subscriptions only at connection granularity —
`TeardownDisconnect` removes "the pub-sub writer and the subscriptions" in one
step, with no component standing for who registered which — so the model's third
consequence ("if this session is still the listener, clear the listener and the
callbacks together, then run the disconnect cascade; otherwise remove nothing at
all") reads, at that granularity, as *skip the cascade when stale*. Refined to
the handler, the same clause reads differently and more exactly: a teardown
removes what it owns by object identity and skips what belongs to others. A
subscription handler is a bound method of the session that registered it, so it
names its owner unambiguously; removing by that identity takes nothing a
successor installed, on any path. That is strictly stronger than skipping, and it
cannot introduce the cross-session removal Invariant 3 forbids — a compare that
fails removes nothing. The same reasoning guards the writer binding, which the
model removes unguarded (sound there only because the cascade shares one loop run
with the detach that authorised it): comparing before removing preserves
Invariant 1 under strictly more interleavings than the model requires, so no
re-run of the model was needed.

T5 is the regression test for defect (A), written against the model's trace:
connect A, connect B under the same identity, register from B, let A's teardown
proceed, then assert B is still the listener, still owns its callback, and still
receives a routed click on its socket. Its necessity was checked the way the
model's variants were — with the ownership guard removed, it fails, and so does
T6.

## Registration

| # | Partition | Audit |
|---|-----------|-------|
| R1 | Gate passes: a listener is registered | covered — `an_identified_listening_session_registers_and_the_menu_is_pushed`, `register_from_on_connect_then_receive_the_click_over_the_websocket` |
| R2 | Gate refuses: no listener at all | covered — `registration_requires_a_push_reachable_connection`, `registering_without_the_leg_is_refused_on_the_production_path`, `a_dropped_listener_closes_the_door_to_new_registrations` |
| R3 | Gate refuses: unidentified session | covered — `registration_still_requires_an_identified_session` |
| R4 | Gate order: push-reachability is answered before identity | covered — `push_reachability_is_answered_before_identity` |
| R5 | Commit with the gated listener still in place | covered — implied by R1 |
| R6 | Commit after the gated listener **tore down** — must refuse | covered — `a_registration_gated_against_a_departed_leg_is_refused` |
| R7 | Commit after the gated listener was **replaced** by a successor — must refuse | covered — `a_registration_gated_against_a_replaced_leg_is_refused` |
| R8 | Gate refuses on a lapsed lease | covered — `a_session_whose_lease_lapsed_is_challenged_rather_than_registered`, `register_callback_refuses_a_lapsed_session` |

R6 is the regression test for defect (B). It was written the second way it
describes, which the fix made possible: `register_callback` now takes the leg the
gate observed, so the test calls it with a leg that is no longer installed and
asserts it refuses and writes nothing. No paused thread is needed, because the
comparison and the write are one critical section.

## Routing, hold, lease

| # | Partition | Audit |
|---|-----------|-------|
| H1 | Click on a registered callback with a live listener → routed and pushed | covered — `a_routed_click_is_pushed_to_the_live_connection`, `a_routed_invocation_wakes_the_connections_listener` |
| H2 | Click with no listener → held, drained on the next connect | covered — `a_click_buffered_before_connect_is_drained_on_connect` |
| H3 | Click for a departed session → `provider_gone` | covered — `a_click_for_a_lapsed_or_absent_session_reports_provider_gone` |
| H4 | Click for an unregistered callback → `unknown_callback` | covered — `a_click_for_an_unregistered_callback_is_unknown` |
| H5 | Hold is bounded; the oldest is dropped, and the drop is reported | covered — `the_hold_is_bounded_dropping_the_oldest`, `a_full_hold_says_which_click_it_drops`, `a_hold_below_its_bound_drops_nothing_and_says_nothing` |
| H6 | Hold is swept when the lease lapses | covered — `a_departed_session_has_its_hold_swept`, `take_sweeps_an_expired_session_without_a_route_in_between` |
| H7 | Holds are never shared between sessions | covered — `two_sessions_never_share_a_hold` |
| H8 | A raising listener is isolated and the click kept — the leg deliberately stays listening, since the slot's only exit is its owner's teardown | covered — `a_raising_listener_is_isolated_and_the_click_is_kept` |
| H9 | A click routed **during** a teardown lands in a hold nothing will drain | **gap** — a nuisance, not an invariant break; worth one test to pin the behaviour |
| H10 | A pumping session's keepalive holds the entry open indefinitely | **gap** — this is what makes a clobbered state permanent rather than self-healing |

The hold and the router are the best-covered part of this system. Every gap
above is in the *lifecycle* — who owns the slot and when — not in the routing.

## Lock discipline

| # | Partition | Audit |
|---|-----------|-------|
| L1 | The live read precedes the router lock; the two never nest | covered — `the_live_read_precedes_the_router_lock` |
| L2 | The listener wake runs outside the router lock | covered — `the_wake_runs_outside_the_router_lock` |
| L3 | The listener slot and the callback set are under **one** lock | covered — `the_leg_and_its_callbacks_are_written_under_one_lock`, instrumented through the registry's own lock in L1's shape |

L1 and L2 are the precedent to copy. Both assert the discipline directly by
instrumenting the lock rather than by observing an outcome, which is why they
are worth having; L3 should be written the same way.

## What the fix must not break

Every currently-passing test in the four files above must still pass. Three
deserve a second look, because the fix changes the code they exercise:

- `a_departed_connections_menu_items_leave_with_it` — still passes, because
  the departing session **is** the listener, so the owned branch fires.
- `a_peer_that_dies_before_the_handshake_leaves_no_listener` — still passes;
  the session installed the listener before the failing write, so it owns it.
- `a_dropped_listener_closes_the_door_to_new_registrations` — still passes,
  and becomes the gate half of R6's pair.

## Summary

Of thirty-five partitions, thirty-three are covered. The two that remain are H9 (a
click routed *during* a teardown lands in a hold nothing drains) and H10 (a
pumping session's keepalive holds the entry open indefinitely). Neither is an
invariant break: H9 is a nuisance the bounded hold absorbs, and H10 is the
property that made a clobbered state permanent — which, with the clobber ruled
out, no longer has a state to preserve.

Every partition that was a gap before the fix was a lifecycle case: two sessions
on one connection, a teardown that is not the current owner's, or a registration
whose gate has gone stale. That distribution was the empirical fingerprint of the
two defects — the routing was tested, the succession was not.
