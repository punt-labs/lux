# Menu presence: coverage audit

Companion to [menu_presence.tex](./menu_presence.tex) (the model),
[menu_presence_locks.tex](./menu_presence_locks.tex) (the lock order), and
their fidelity controls. The model proves, for the fixed design, two
invariants over a bounded carrier (`DEFAULT_SETSIZE 3`, 9000 states, 180801
transitions, no deadlock, no counter-example):

- **P1** with no mark pending, the set the Display shows equals the set of
  sessions that earn menu presence.
- **P2** every registered session that earns presence has exactly one bound
  menu sink; none has more; a departed session has none.

This audit derives test partitions from the model's operations, maps each to
the tests that exist in `tests/`, and names the tests that do not exist yet
precisely enough to write. A partition marked **MISSING** is a gap: a passing
suite today says nothing about it.

## The fix design the model proves

1. **Presence is event-driven.** A session earns presence while it is
   registered and an agent. Only a registry departure (sweep or graceful
   drop) removes it. A lapsed-but-unswept lease is not a presence change, and
   neither is the renewal that ends it. `NamedSessions` stops filtering the
   presence roster by lease liveness (it keeps the filter for the reads that
   mean "live", such as `list_clients`). This deletes D4 by construction: with
   no time filter there is nothing for a renewal to undo. It is a one-line
   amendment to DES-064 ("an entry exists while its registrant is registered;
   registration ends at the lease reap"), costing at most one sweep interval
   (15 s) of a lapsed entry's visibility, where today its visibility ends at
   an arbitrary unrelated push. It is consistent with DES-057 (leases expire
   state by reaping it), DES-094 (liveness is a heuristic), and
   `menu_lifecycle.tex` MO, which is already stated over `registered`.
2. **One transition, owned by `HubDisplay`.** The upsert that records an
   agent (`identify`, listen attach, the read loop's per-frame `record`) and
   the removal that departs one are each a single `HubDisplay` method that
   holds the store write lock, calls the registry, and, if the registry
   reports that presence changed, marks the menus and binds the one shared
   sink, before releasing. Callers compare nothing and remember nothing.
   `MenuArming.track` and `Operations.identify`'s `before` snapshot go away.
   `ws_listen._read_loop` stops calling `HubClientRegistry.record` directly.
3. **The registry never calls out of its own lock.** Firing the hook from
   inside `HubClientRegistry.record` (the "registry owns it" shape) takes the
   store lock under the registry lock, the reverse of every existing path.
   `menu_presence_locks_inverted_buggy.tex` finds the deadlock in three steps;
   `menu_presence_locks.tex` shows the order above (store, then registry;
   readers registry-only) has none.
4. **One shared sink object.** `DepartureSinks.bind` already dedups by
   equality; the fix is to bind one `MenuDepartureSink`-shaped object (no
   per-attach lambda). `_teardown` need not unbind it: the sink belongs to the
   session, which outlives its socket.

The alternative the task named, "registry owns presence and raises the mark
itself", is right about ownership and wrong about the lock: the owner is the
`HubDisplay` method that wraps the registry, not the registry.

## Fidelity of the model

Each defect is reproduced by a control that differs from the fixed model in
one operation, and each produces a counter-example. Full commands are in the
header of each file.

| Defect | File | Negation found | Witness (ProB) |
|---|---|---|---|
| D1/D2 identify or attach never marks | `menu_presence_d1_buggy.tex` | P1 | `Identify(c)` |
| D3 read loop revives a swept session | `menu_presence_d3_buggy.tex` | P1 and P2 | `Attach(c); DropGraceful(c); Push; ReadLoopRecord(c)` |
| D4 presence filtered by lease time | `menu_presence_d4_buggy.tex` | P1 (with `lapsed = {}`) | `Identify(c); LeaseLapse(c); Push; Renew(c)` |
| D5 before-snapshot outside the lock | `menu_presence_d5_buggy.tex` | P1 and P2 | `Attach(c); IdentifyRead(c); DropGraceful(c); Push; IdentifyWrite(c)` |
| D6 a sink per attach | `menu_presence_d6_buggy.tex` | P2 | `Attach(c); Attach(c)` |
| registry-owned hook | `menu_presence_locks_inverted_buggy.tex` | deadlock | `BeginWrite(t1); BeginRegistryWrite(t2)` |

## Partitions

A partition is an operation crossed with the cases its guard and its
frame distinguish. "Marks" means `mark_menus` is raised; "sink" means the
connection has exactly one bound menu sink afterwards.

### AgentRecord (identify, attach, read-loop record)

| # | Partition | Expected | Existing test | Status |
|---|---|---|---|---|
| A1 | identify, unregistered connection, agent identity | marks; sink; entry listed | `tests/operations/test_identity_menu.py::test_identifying_a_callbackless_agent_marks_menus_and_it_is_listed` | covered (sink count not asserted, see S1) |
| A2 | identify, registered anonymous connection (Connect first), becomes agent | marks; sink | none | **MISSING** |
| A3 | identify again, already earning, identical declaration | no mark; sink unchanged | `test_repeating_an_identical_identify_marks_menus_once` | covered |
| A4 | identify again, already earning, changed declaration (new repo) | entry relabelled by a push | `test_re_identifying_marks_menus_again` | covered (under the model's rule this is not a presence change; the test pins the labelled-entry behaviour, which the fix must keep) |
| A5 | listen attach of an agent, first time | marks; sink | `tests/test_ws_listen.py::test_a_listen_attach_of_an_agent_marks_menus_and_its_lapse_withdraws_it` | covered (sink count not asserted) |
| A6 | listen attach of an agent, reconnect over a live session | sink count stays one | none | **MISSING** (D6) |
| A7 | read-loop record on a registered session | renewal only; no mark | none | **MISSING** |
| A8 | read-loop record on a session the sweep removed, socket still open | marks; sink re-bound; entry shown | none | **MISSING** (D3) |
| A9 | departure lands between the facade's snapshot and the record | marks; sink bound | `test_a_departure_cannot_interleave_with_binding_the_sink` covers only track's check-then-bind, not the snapshot window | **MISSING** (D5) |
| A10 | non-agent identify (a cli) | no mark; no sink | none | **MISSING** |

### Departure (graceful drop, lease sweep)

| # | Partition | Expected | Existing test | Status |
|---|---|---|---|---|
| D-1 | graceful drop of an earning agent | marks; entry gone; sink fired and unbound | `test_its_departure_marks_menus_and_the_entry_is_gone` | covered |
| D-2 | sweep of a lapsed earning agent | marks; entry gone | `test_a_lease_lapse_reap_marks_menus_and_the_entry_is_gone`, `tests/domain/test_menu_departure_cascade.py::test_a_lease_lapse_departure_marks_the_menu_bar_for_re_push` | covered |
| D-3 | sweep of a lapsed agent attached by the listen leg | marks; entry gone | `test_a_listen_attach_of_an_agent_marks_menus_and_its_lapse_withdraws_it` | covered |
| D-4 | departure of a non-earning session | no mark | none | **MISSING** |
| D-5 | departure of a connection whose socket is still open | socket survives; registry/sink released; a later frame revives it (see A8) | none | **MISSING** |
| D-6 | a revived session (A8) later departs | marks; entry gone (no ghost) | none | **MISSING** (the ghost half of D3 and D5) |

### Lapse and renewal (the D4 cluster)

| # | Partition | Expected | Existing test | Status |
|---|---|---|---|---|
| L1 | agent's lease lapses, no sweep | still listed; no mark | none | **MISSING** |
| L2 | lapsed, unswept agent, another client's push | the push still lists the agent | none | **MISSING** (D4) |
| L3 | lapsed agent renewed by any contact (REST write, MCP call) | still listed; no mark | none | **MISSING** (D4) |
| L4 | a renewing agent keeps its entry across reap opportunities | listed | `test_a_renewing_menu_owner_keeps_its_bar_across_reap_opportunities` (menu owner, not agent) | partial |

### Sinks (P2)

| # | Partition | Expected | Existing test | Status |
|---|---|---|---|---|
| S1 | after attach/identify, the connection has exactly one menu sink | `len == 1` | none asserts a count; `tests/domain/test_departure_sinks.py::test_binding_the_same_sink_twice_fires_it_once` covers the dedup of one object | **MISSING** at the integration point |
| S2 | N reconnects of one identity | still one sink; no growth | none | **MISSING** (D6) |
| S3 | the sink bound by `ws_listen` compares equal across attaches | one object | none | **MISSING** (D6) |
| S4 | departure fires and unbinds; `sinks` zero afterwards | zero | `test_fire_unbinds_so_a_second_fire_is_a_noop` (unit) | covered at unit level |
| S5 | the pinned object: a dead `HubListenSession` is not referenced by any bound sink after teardown or departure | no reference | none | **MISSING** (D6; a `gc`/`weakref` check) |

### Push (P1)

| # | Partition | Expected | Existing test | Status |
|---|---|---|---|---|
| P-1 | push with a mark pending shows exactly the earning set | shown == earning | `tests/domain/test_hub_replicator.py` (menu leg), `tests/integration/test_clients_menu_round_trip.py` | covered |
| P-2 | **the P1 sweep**: a randomised sequence of identify, attach, read-loop record, lapse, renew, sweep, drop, teardown, push, run against the real `HubDisplay`; after every step with no mark pending the pushed roster equals `earns_menu_presence` over the registry | the model's invariant, executable | none | **MISSING** (the strongest single test) |

### Lock order

| # | Partition | Expected | Existing test | Status |
|---|---|---|---|---|
| K1 | `HubClientRegistry.record`, `attach_listener`, `discard`, `reap_lapsed_locked` complete while another thread holds the store write lock | the registry never waits on the store lock | none | **MISSING** |
| K2 | a presence-changing write routed through `HubDisplay` with the registry lock contended by a reader completes | no deadlock | none | **MISSING** |

## Missing tests, named for the implementer

Each name is a test function; the file is where it belongs.

`tests/operations/test_identity_menu.py`

- `test_identifying_an_anonymous_registered_connection_as_an_agent_marks_menus_and_binds_one_sink` (A2)
- `test_a_cli_identify_marks_nothing_and_binds_no_sink` (A10)
- `test_identify_binds_exactly_one_menu_sink` (S1; assert through a `DepartureSinks` spy or the cascade's bound list)
- `test_a_departure_between_the_before_snapshot_and_the_record_still_marks_and_binds` (A9). Drive it by dropping the connection from the intruder inside `IdentityOperations.identify` after it has read `current`; under the fixed design there is no snapshot, so the test asserts the end state: marks raised, one sink, entry listed, and then that a later departure marks again (D-6).
- `test_a_lapsed_unswept_agent_stays_listed_and_marks_nothing` (L1)
- `test_a_lapsed_unswept_agent_survives_another_clients_push` (L2)
- `test_renewing_a_lapsed_agent_marks_nothing_and_keeps_its_entry` (L3)
- `test_a_non_agent_departure_marks_nothing` (D-4)

`tests/test_ws_listen.py`

- `test_a_read_loop_frame_on_a_registered_session_only_renews` (A7)
- `test_a_swept_session_with_an_open_socket_is_revived_by_the_next_frame_marking_menus_and_binding_one_sink` (A8, D3)
- `test_a_revived_session_departs_with_a_mark_not_a_ghost` (D-6)
- `test_reconnecting_the_same_identity_n_times_leaves_one_menu_sink` (A6, S2, D6)
- `test_the_menu_sink_ws_listen_binds_is_the_same_object_on_every_attach` (S3)
- `test_no_bound_sink_references_a_departed_listen_session` (S5)

`tests/domain/test_hub_clients_lock_order.py` (new; mirrors `hub_clients.py`)

- `test_record_does_not_wait_on_the_store_lock` (K1; hold `display.write_lock()` in the test thread, call `record` from a second thread with a short join, assert it completes)
- `test_attach_listener_does_not_wait_on_the_store_lock` (K1)
- `test_a_presence_write_through_hub_display_completes_while_a_reader_holds_the_registry_lock` (K2)

`tests/domain/test_menu_presence_model.py` (new; the executable P1/P2)

- `test_after_every_step_with_no_mark_pending_the_pushed_roster_is_the_earning_set` (P-2). Seeded random walk of the model's operations against a real `HubDisplay`, a recording `DirtyMarker`, and the production replicator push; checks P1 after every step and P2 (`bound sink count`) for every connection. Failing seeds are printed; a regression test pins each one.

## Definition of done for the implementation mission

1. Every **MISSING** partition above has a test, each failing before the fix
   and passing after it (D3, D4, D5, D6 first: they are the open defects).
2. `menu_presence.tex` and the five controls re-run unchanged: the fixed spec
   reports P1 and P2 not found; each control reports its negation found; the
   lock model reports no deadlock and its inverted control a deadlock.
3. DES-064 carries the one-line amendment from "The fix design" item 1, and
   the lux `DESIGN.md` entry for this work cites DES-057, DES-064, DES-067,
   DES-094 and DES-098.
