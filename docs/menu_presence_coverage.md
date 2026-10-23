# Menu presence: coverage audit

Companion to [menu_presence.tex](./menu_presence.tex) (the model),
[menu_presence_locks.tex](./menu_presence_locks.tex) (the lock order), and
their fidelity controls. This is an audit of `tests/` against the model, not a
plan: every partition below is mapped to the test that covers it today, or
marked **MISSING**, and the tests the implementation mission added are listed
at the end. Audited against the tests as they stand on `fix/lux-ghhf-details-frame-id`
(the model mission writes none).

The model proves three invariants for the fixed design over a bounded carrier
(`DEFAULT_SETSIZE 2`, 18,900 states, 453,277 transitions, no deadlock, no
counter-example; see the size-3 note under "Fidelity of the model"):

- **P1** with no mark pending, no live session that earns menu presence is
  missing from the Display and nothing it shows is unregistered. A lapsed
  entry may linger, but only until the sweep or the next push.
- **P2** every registered session that earns presence has exactly one bound
  menu sink; none has more; a departed session has none.
- **P3** per connection: a live session's frame shows its current label unless
  that session's own scenes carry a pending mark. A lapsed survivor's frame may
  stay stale only until its revival, and the revival marks its scenes. (With no
  scene mark pending at all, no live frame is stale: the global corollary.)

A session earns presence two ways: it is an agent (kind alone), or it holds a
callback. The callback route is what the earlier revision of the model elided
and what hid the first of the two defects below.

## The two defects this revision models

| Finding | Shape | Model step that fixes it |
|---|---|---|
| INV-1 | The listener-leg writes (then `ListenerLegs`, now `PresenceWrites.register_callback` and `detach`) wrote presence under the registry lock only, from `CallbackOperations` and `ws_listen`, with no store lock, no sink bound, the mark raised by hand. A lapse then departs the session with no sink to fire: the entry lingers past the sweep (P1, P2). | `RegisterCallback` and `Detach` are `ClientLifecycle` steps: store lock, then registry lock, then mark and bind the one shared sink. |
| INV-2 | A survivor renumbered while its lease is lapsed-but-unswept is resolved to no label (`FrameOwnerFacts.facts_for` reads live sessions only); a later renewal marks the menus and never the survivor's scenes. | Every step that ends a lapse (`Renew`, `Connect`, `AgentRecord`, `AppletAttach`, `RegisterCallback`) also marks the connection's scenes. |

## What the model adds that the findings do not say (INV-1b, M1)

`MenuListing.change_to` compares *lease-filtered* listings, so a withdrawal made
during a lapse is invisible to it. A lapsed callback-only applet whose entry is
still on the Display, and whose callbacks are then withdrawn (`detach`, or a
re-attach that clears them), is neither listed before nor after: it reads
`unchanged` and no mark is raised. A re-attach renews the lease, so the session
is then live, non-earning and still shown; it keeps renewing, is never swept, and
the entry stays for good. Witness (`menu_presence_inv1b_buggy.tex`):
`AppletAttach(c); RegisterCallback(c); Push; LeaseLapse(c); AppletAttach(c)`,
reaching the goal "no mark pending and a registered, live, non-earning session
is shown". The same root makes **M1** a ghost: a lapsed agent that re-identifies
as a non-agent (a `cli`) reads `unchanged` and is renewed; witness
(`menu_presence_redeclare_buggy.tex`): `Identify(c); Push; LeaseLapse(c);
Redeclare(c)`.

The code before this fix was right by accident for `detach`: `ws_listen._teardown`
marked by hand and `Attachment.menu_change` (since removed) turned
`attached_over_callbacks` into `revised`. It was not right for re-identification.

**The rule, stated once, in `MenuListing`:** a session that *earned before,
ignoring the lease*, and does not earn after, reads `revised`, whatever the lease
says; the registered entries are part of what it compares, so a lapsed session
that loses entries reads `revised` and so does any entry added, withdrawn or
relabelled on a listed one. That single rule covers `detach`, attach-over-callbacks and re-identify as
a non-agent together; a gain still reads the lease (not live before, live and
earning after, is `gained`). The implementer puts it where every route passes
rather than adding a mark per step.

Likewise the INV-2 repair must key on the lapse ending (the session was not
live, now is), not on `PresenceChange == "gained"`: a session that earns
nothing (a `cli`) has a label too, and its revival is `unchanged` for the menu.

## The fix design the model proves

1. **Presence is lease-filtered, per the settled ADRs; no lease ADR is amended.**
   DES-101 is amended for the callback route, which passes through the lifecycle.
   A session earns presence while it is registered, earning (an agent, or
   holding a callback), and its lease is live: DES-058 ("entries live on the
   session's lease and leave when it lapses"), DES-064 §1 ("an entry exists
   exactly while its registrant holds a lease"), DES-057 ("leases expire state
   whose owner left"). A lapse is time, not a Hub event: it cannot mark, and a
   lapsed entry may linger until the sweep or the next push. A renewal that
   revives a lapsed session is a presence transition: it marks and re-asserts
   the one shared sink.
2. **One transition, owned by `ClientLifecycle`.** `arrive`, `identify`,
   `attach`, `renew`, `register_callback`, `detach`, `depart`, `depart_lapsed`
   are each a single method that holds the store write lock, calls the
   registry's write surface (`PresenceWrites`, taken once by `ClientLifecycle`), and settles
   what the write owes the Hub: the menu mark, the one sink, the scene marks of a
   revived session. Callers compare nothing and remember nothing.
   `CallbackOperations` and `ws_listen` are no longer handed `PresenceWrites` for
   these writes.
3. **The registry never calls out of its own lock.** Firing the hook from inside
   the registry (or `PresenceWrites`) takes the store lock under the registry
   lock, the reverse of every existing path. `menu_presence_locks_inverted_buggy.tex`
   finds the deadlock in three steps; `menu_presence_locks.tex` shows the order
   (store, then registry; readers registry-only), callback steps included, has
   none.
4. **One shared sink object** (`MarkMenusSink`). `DepartureSinks.bind` dedups by
   equality, so rebinding is a no-op, and `detach` need not unbind it.

## Fidelity of the model

Each defect is reproduced by a control that differs from the fixed model in one
operation (INV-2: one rule applied at each revival step), and each produces a
counter-example. Every file carries its own commands in its header.

| Defect | File | Negation found | Witness (ProB) |
|---|---|---|---|
| D1/D2 identify or attach never marks | `menu_presence_d1_buggy.tex` | P1 | `Identify(c)` |
| D3 read loop revives a lapsed or swept session | `menu_presence_d3_buggy.tex` | P1 and P2 | `AppletAttach(c); ReadLoopRecord(c)`; also `Attach(c); LeaseLapse(c); Push; ReadLoopRecord(c)` |
| D4 renewing a lapsed agent never marks | `menu_presence_d4_buggy.tex` | P1 | `Identify(c); LeaseLapse(c); Push; Connect(c)` |
| D5 before-snapshot outside the lock | `menu_presence_d5_buggy.tex` | P1 and P2 | `Attach(c); IdentifyRead(c); DropGraceful(c, {}); Push; IdentifyWrite(c)` |
| D6 a sink bound per attach | `menu_presence_d6_buggy.tex` | P2 | `Identify(c); Attach(c)` |
| INV-1 callback written under the registry lock only, no sink | `menu_presence_inv1_buggy.tex` | P2 and P1 | P2: `AppletAttach(c); RegisterCallback(c)`; P1: the same, then `Push; DropGraceful(c, {})` |
| INV-1b withdrawal mark gated on the lease | `menu_presence_inv1b_buggy.tex` | P1 | `AppletAttach(c); RegisterCallback(c); Push; LeaseLapse(c); AppletAttach(c)` (live ghost; `Detach(c)` last leaves the lapsed variant) |
| INV-2 a revival marks the menus, not the scenes | `menu_presence_inv2_buggy.tex` | P3 (per connection) | `Connect(c1); Connect(c2); LeaseLapse(c1); DropGraceful(c2, {c1}); PushScenes; Renew(c1)` |
| M1 withdrawal mark gated on the lease, on re-identify as a non-agent | `menu_presence_redeclare_buggy.tex` | P1 | `Identify(c); Push; LeaseLapse(c); Redeclare(c)` |
| registry-owned hook | `menu_presence_locks_inverted_buggy.tex` | deadlock | `BeginRegistryWrite(t2); BeginCallbackWrite(t1)` (also `BeginWrite(t1); BeginRegistryWrite(t2)`) |

All nine state-model controls and the lock control were run at `DEFAULT_SETSIZE 2`
and found their negation. The controls are generated from the fixed model, so
each differs from it in its one defect (INV-1b and INV-2 apply one rule at each
of its sites). In particular d3, d5 and d6 keep the revival's scene mark.

## Partitions

A partition is an operation crossed with the cases its guard and its frame
distinguish. "Marks" means `mark_menus` is raised; "sink" means the connection
has exactly one bound menu sink afterwards. Identifiers: **A** agent record,
**C** callback route, **DP** departure, **L** lapse and renewal, **B** label,
**S** sinks, **P** push, **K** lock order.

### A: AgentRecord (identify, attach, read-loop record)

| # | Partition | Expected | Covering test | Status |
|---|---|---|---|---|
| A1 | identify, unregistered connection, agent identity | marks; sink; listed | `tests/operations/test_identity_menu.py::test_identifying_a_callbackless_agent_marks_menus_and_it_is_listed` | covered |
| A2 | identify, registered anonymous connection, becomes agent | marks; sink | `test_identity_menu.py::test_identifying_an_anonymous_registered_connection_as_an_agent_marks_menus_and_binds_one_sink` | covered |
| A3 | identify again, identical declaration | no mark; sink unchanged | `test_identity_menu.py::test_repeating_an_identical_identify_marks_menus_once` | covered |
| A4 | identify again, changed declaration | entry relabelled | `test_identity_menu.py::test_re_identifying_marks_menus_again` | covered (a revision, not a presence change in the model) |
| A5 | listen attach of an agent, first time | marks; sink | `tests/test_ws_listen.py::test_a_listen_attach_of_an_agent_marks_menus_and_its_lapse_withdraws_it` | covered |
| A6 | listen attach, reconnect over a live session | sink count stays one | `test_ws_listen.py::test_reconnecting_the_same_identity_n_times_leaves_one_menu_sink` | covered |
| A7 | read-loop frame on a registered live session | renewal only; no mark | `test_ws_listen.py::test_a_read_loop_frame_on_a_live_session_only_renews` | covered |
| A8 | read-loop frame on a session the sweep removed, socket open | marks; sink re-bound; listed | `test_ws_listen.py::test_a_swept_session_with_an_open_socket_is_revived_by_the_next_frame_marking_menus_and_binding_one_sink` | covered |
| A9 | departure lands just before the record | marks; one sink; later departure marks | `test_identity_menu.py::test_a_departure_landing_before_the_record_still_marks_and_binds` (the before-snapshot window itself no longer exists; the test pins the end state under the lock) | covered |
| A10 | non-agent identify (a cli) | no mark; no sink | `test_identity_menu.py::test_a_cli_identify_marks_nothing_and_binds_no_sink` | covered |
| A11 | the record and the bind are one step | a departure cannot interleave | `test_identity_menu.py::test_a_departure_cannot_interleave_with_binding_the_sink` | covered |
| A12 | a lapsed agent re-identifies as a non-agent (a `cli`) | marks; its entry is gone; scenes marked; no ghost after the lease renews | `tests/domain/test_client_lifecycle_callbacks.py::TestReDeclaring::test_a_lapsed_agent_re_identifying_as_a_cli_marks_and_stays_gone`, `::test_a_live_agent_re_identifying_as_a_cli_marks`; the rule itself: `::TestTheWithdrawalRule::test_a_live_withdrawal_is_revised`, `::test_a_lapsed_withdrawal_is_revised_too`, `::test_a_session_that_never_earned_reads_unchanged`, `::test_a_gain_still_reads_the_lease` | covered |

### C: the callback route (INV-1)

| # | Partition | Expected | Covering test | Status |
|---|---|---|---|---|
| C1 | non-agent attach (applet), no callback | registered, leg open; no mark; no sink | `test_ws_listen.py::test_a_first_leg_with_no_entries_to_clear_asks_for_no_menu_push` (marks only; the sink count is not asserted) | partial |
| C2 | `register_callback` on an attached, identified, live applet | marks; exactly one sink; entry listed | `tests/operations/test_callback_operations.py::test_an_identified_listening_session_registers_and_the_menu_is_pushed` (mark, listing), `::test_registering_a_callback_binds_exactly_one_menu_sink` (sink); `tests/domain/test_client_lifecycle_callbacks.py::TestRegistering::test_marks_the_menus_and_binds_exactly_one_sink`, `::test_registering_again_still_leaves_one_sink` | covered |
| C3 | the INV-1 regression: applet attach, `register_callback`, lapse, `depart_lapsed` | the departure marks; exactly one sink fired; entry gone | `tests/domain/test_client_lifecycle_callbacks.py::TestRegistering::test_an_applet_that_registers_then_lapses_is_departed_with_one_mark` | covered |
| C4 | `register_callback` is a `ClientLifecycle` step: the store lock is held while the leg is written | no write to the registry's callbacks outside the store lock | `tests/domain/test_client_lifecycle_callbacks.py::TestRegistering::test_is_one_step_under_the_store_lock`; `::TestDetaching::test_is_one_step_under_the_store_lock` (detach) | covered |
| C5 | `register_callback` revives a lapsed, still-reachable applet | marks; one sink; scenes marked | `tests/operations/test_callback_operations.py::test_registering_on_a_lapsed_reachable_applet_marks_menus_and_binds_one_sink`; `tests/domain/test_client_lifecycle_callbacks.py::TestRegistering::test_revives_a_lapsed_but_reachable_applet_with_one_sink_and_marks_its_scenes` | covered |
| C6 | `detach` of a callback-only applet | marks; entry gone; session, lease and sink persist | `tests/domain/test_client_lifecycle_callbacks.py::TestDetaching::test_a_callback_only_applet_withdraws_its_entry_and_keeps_session_and_sink`; also `tests/test_ws_listen.py::test_a_departed_connections_menu_items_leave_with_it` | covered |
| C7 | `detach` of a lapsed callback-only applet whose entry is still shown (INV-1b) | marks; entry gone | `tests/domain/test_client_lifecycle_callbacks.py::TestDetaching::test_a_lapsed_callback_only_applet_still_marks_the_withdrawal` | covered |
| C8 | `detach` of an agent holding callbacks | no entry change; sink persists | `tests/domain/test_client_lifecycle_callbacks.py::TestDetaching::test_an_agent_holding_callbacks_stays_listed_and_keeps_its_sink` | covered |
| C9 | `detach` by a session that lost the slot | clears nothing; marks nothing | `test_ws_listen.py::test_a_superseded_sessions_teardown_leaves_its_successor_whole`, `test_hub_clients.py::test_a_teardown_by_a_session_that_lost_the_slot_removes_nothing` | covered |
| C10 | re-attach clears the predecessor's callbacks | marks | `test_ws_listen.py::test_a_new_leg_arrives_with_none_of_its_predecessors_menu_entries`, `test_hub_clients.py::test_attaching_over_callbacks_revises_the_menu_though_presence_held` | covered (live case) |
| C11 | re-attach clears callbacks of a lapsed applet (INV-1b) | marks | `tests/domain/test_client_lifecycle_callbacks.py::TestAttachingOverCallbacks::test_the_callbacks_of_a_lapsed_applet_are_cleared_with_a_mark` | covered |
| C12 | `register_callback` refused (no leg, anonymous, superseded) | nothing marks, nothing binds | `test_callback_operations.py::test_registration_requires_a_push_reachable_connection`, `test_a_dropped_listener_closes_the_door_to_new_registrations`; `test_hub_clients.py::test_register_callback_refuses_an_unknown_session`, `test_register_callback_refuses_a_lapsed_session`, `test_a_registration_gated_against_a_departed_leg_is_refused`, `test_a_registration_lands_on_the_leg_that_now_holds_the_connection` | covered |

### DP: departure (graceful drop, lease sweep)

| # | Partition | Expected | Covering test | Status |
|---|---|---|---|---|
| DP1 | graceful drop of an earning agent | marks; entry gone; sink fired and unbound | `test_identity_menu.py::test_its_departure_marks_menus_and_the_entry_is_gone` | covered |
| DP2 | sweep of a lapsed earning agent | marks; entry gone | `test_identity_menu.py::test_a_lease_lapse_reap_marks_menus_and_the_entry_is_gone`; `tests/domain/test_menu_departure_cascade.py::test_a_lease_lapse_departure_marks_the_menu_bar_for_re_push` | covered |
| DP3 | sweep of a lapsed agent attached by the listen leg | marks; entry gone | `test_ws_listen.py::test_a_listen_attach_of_an_agent_marks_menus_and_its_lapse_withdraws_it` | covered |
| DP4 | departure of a non-earning session | no mark | `test_identity_menu.py::test_a_non_agent_departure_marks_nothing` | covered |
| DP5 | departure of a connection whose socket is still open | registry and sink released; a later frame revives (see A8) | `test_ws_listen.py::test_a_swept_session_with_an_open_socket_is_revived_by_the_next_frame_marking_menus_and_binding_one_sink` | covered |
| DP6 | a revived session later departs | marks; entry gone (no ghost) | `test_ws_listen.py::test_a_revived_session_departs_with_a_mark_not_a_ghost` | covered |
| DP7 | departure (graceful or sweep) of a callback-only applet | marks via its sink; entry gone | `tests/domain/test_client_lifecycle_callbacks.py::TestRegistering::test_a_callback_only_applet_departs_with_a_mark_when_dropped` (graceful), `::test_an_applet_that_registers_then_lapses_is_departed_with_one_mark` (sweep) | covered |
| DP8 | the sweep departs every lapsed agent in one pass | marks; both gone | `test_identity_menu.py::test_the_sweep_removes_every_lapsed_agent_with_a_mark` | covered |

### L: lapse and renewal (the D4 cluster)

| # | Partition | Expected | Covering test | Status |
|---|---|---|---|---|
| L1 | lease lapses, no sweep, no push | nothing marks | `test_identity_menu.py::test_a_lease_lapse_alone_marks_nothing` | covered |
| L2 | lapsed unswept agent, then another client's push | the push drops it | `test_identity_menu.py::test_another_clients_push_drops_a_lapsed_unswept_agent` | covered |
| L3 | the dropped agent renewed by a REST write | marks; entry restored | `test_identity_menu.py::test_a_rest_write_renewing_a_lapsed_agent_marks_menus_and_restores_its_entry` | covered |
| L3b | renewed by an MCP call with unchanged identity | marks; entry restored | `test_identity_menu.py::test_an_mcp_call_renewing_a_lapsed_agent_marks_menus_and_restores_its_entry` | covered |
| L3c | renewed by the read loop's frame | marks; entry restored | `test_ws_listen.py::test_a_read_loop_frame_renewing_a_lapsed_agent_marks_menus_and_restores_its_entry` | covered |
| L3d | renewal of a live agent | no mark | `test_identity_menu.py::test_repeating_an_identical_identify_marks_menus_once`; `test_ws_listen.py::test_a_read_loop_frame_on_a_live_session_only_renews` | covered |
| L3e | one sink after the revival | exactly one | `test_identity_menu.py::test_renewing_a_lapsed_agent_leaves_exactly_one_menu_sink` | covered |
| L4 | a renewing menu owner keeps its bar across reap opportunities | listed | `tests/domain/test_menu_departure_cascade.py::test_a_renewing_menu_owner_keeps_its_bar_across_reap_opportunities` (menu owner, not agent) | partial |
| L5 | `renew_if_registered` and `record` report a revival as `gained` | `gained` | `test_hub_clients.py::test_record_reports_a_lapsed_agents_renewal_as_gained`, `test_renew_if_registered_reports_a_revival_and_never_registers` | covered |

### B: the label of a renumbered survivor (INV-2)

| # | Partition | Expected | Covering test | Status |
|---|---|---|---|---|
| B1 | a departure that frees a base name marks the survivor's scenes | survivor's scenes marked | `tests/domain/test_label_churn.py::test_the_survivor_that_inherits_the_base_name_is_marked` | covered |
| B2 | the lease sweep marks the survivor the same way | marked | `test_label_churn.py::test_a_lease_sweep_marks_the_survivor_the_same_way` | covered |
| B3 | a departure that moves no name marks nothing | nothing | `test_label_churn.py::test_a_departure_that_moves_no_name_marks_nothing` | covered |
| B4 | naming a connection marks its scenes | marked | `test_label_churn.py::test_naming_a_connection_marks_the_scenes_it_already_shows` | covered |
| B5 | a lapsed-but-unswept owner resolves to no label (the premise of INV-2) | `facts_for` reports empty | `tests/domain/test_label_revival.py::TestTheLabelFollowsTheRevival::test_a_lapsed_unswept_owner_reports_no_label` | covered |
| B6 | revival by `renew` marks the connection's scenes | marked | `tests/domain/test_label_revival.py::TestEveryStepThatEndsALapseMarksTheScenes::test_renew` | covered |
| B7 | revival by `arrive` marks them | marked | `tests/domain/test_label_revival.py::TestEveryStepThatEndsALapseMarksTheScenes::test_arrive` | covered |
| B8 | revival by `identify` (an MCP call) marks them | marked | `tests/domain/test_label_revival.py::TestEveryStepThatEndsALapseMarksTheScenes::test_identify_with_the_same_declaration` | covered |
| B9 | revival by `attach` (listen leg) marks them | marked | `tests/domain/test_label_revival.py::TestEveryStepThatEndsALapseMarksTheScenes::test_attach` | covered |
| B10 | revival by the read loop's frame marks them | marked | `tests/test_ws_listen.py::test_a_read_loop_frame_from_a_lapsed_survivor_marks_its_scenes` | covered |
| B11 | revival by `register_callback` marks them | marked | `tests/domain/test_label_revival.py::TestEveryStepThatEndsALapseMarksTheScenes::test_register_callback` | covered |
| B12 | revival of a session that earns nothing (a cli) marks its scenes | marked (this is the lapse, not the presence change) | `tests/domain/test_label_revival.py::TestEveryStepThatEndsALapseMarksTheScenes::test_a_session_that_earns_nothing_is_revived_too` | covered |
| B13 | renewal of a live session marks no scenes | nothing | `tests/domain/test_label_revival.py::TestEveryStepThatEndsALapseMarksTheScenes::test_a_live_renewal_marks_no_scenes` | covered |
| B14 | an empty push evicts the oldest scene while the new owner is lapsed (`relabel(None)`); revival repairs the label | label restored after revival | `tests/domain/test_label_revival.py::TestTheLabelFollowsTheRevival::test_an_emptied_frame_blanked_for_a_lapsed_owner_is_repaired_by_revival` | covered |
| B15 | end to end: renumber a lapsed survivor, push, renew it, push | the frame shows the current label | `tests/domain/test_label_revival.py::TestTheLabelFollowsTheRevival::test_a_renumbered_lapsed_survivor_shows_its_current_label_after_reviving` | covered |

### S: sinks (P2)

| # | Partition | Expected | Covering test | Status |
|---|---|---|---|---|
| S1 | after identify, one sink | one | `test_identity_menu.py::test_identify_binds_exactly_one_menu_sink` | covered |
| S2 | N reconnects of one identity | still one | `test_ws_listen.py::test_reconnecting_the_same_identity_n_times_leaves_one_menu_sink` | covered |
| S3 | the sink `ws_listen` binds compares equal across attaches | one object | `test_ws_listen.py::test_the_menu_sink_ws_listen_binds_is_the_same_object_on_every_attach` | covered |
| S4 | departure fires and unbinds | zero afterwards | `tests/domain/test_departure_sinks.py::test_fire_unbinds_so_a_second_fire_is_a_noop`, `test_binding_the_same_sink_twice_fires_it_once` | covered at unit level |
| S5 | no bound sink references a departed listen session | no reference | `test_ws_listen.py::test_no_bound_sink_references_a_departed_listen_session` | covered |
| S6 | `MenuPresence` binds the same sink object on every announcement | one object | `tests/domain/test_menu_presence.py::test_every_announcement_binds_the_same_sink_object` | covered |
| S7 | a callback-only applet has exactly one sink after `register_callback`, none after `depart` | one; zero | `tests/domain/test_client_lifecycle_callbacks.py::TestRegistering::test_marks_the_menus_and_binds_exactly_one_sink`, `::test_registering_again_still_leaves_one_sink`, `::test_a_callback_only_applet_departs_with_a_mark_when_dropped`; `tests/operations/test_callback_operations.py::test_registering_a_callback_binds_exactly_one_menu_sink` | covered |

### P: push (P1)

| # | Partition | Expected | Covering test | Status |
|---|---|---|---|---|
| P-1 | push with a mark pending shows exactly the earning set | shown equals earning | `tests/domain/test_hub_replicator.py::test_menu_state_is_pushed_from_a_fresh_registry_read`; `tests/integration/test_clients_menu_round_trip.py::test_the_display_draws_what_the_hub_composed` | covered |
| P-2 | the executable invariants: a seeded random walk of the model's operations against the real lifecycle, a recording marker and the production roster and label readers; after every step P1 (live earning sessions in the roster, nothing unregistered shown), P2 (a departing earning session fires exactly one sink, none more) and P3 (a live session's scenes show the current label unless a mark is pending) | P1, P2, P3 | `tests/domain/test_menu_presence_model.py::test_every_invariant_holds_after_every_step` (parametrised over seeds; P2 is observed at departure, not as a bound-sink count) | covered |

### K: lock order

| # | Partition | Expected | Covering test | Status |
|---|---|---|---|---|
| K1 | `PresenceWrites.record`, `renew_if_registered`, `discard`, `reap_lapsed`, `attach`, `register_callback` and `detach` complete while another thread holds the store write lock | the registry never waits on the store lock | `tests/domain/test_client_lifecycle_lock_order.py::TestRegistryWritesNeverWaitOnTheStoreLock::test_every_registry_write_completes_while_the_store_lock_is_held` | covered |
| K2 | a presence-changing `ClientLifecycle` step (including `register_callback` and `detach`) completes while a reader holds the registry lock | no deadlock | `tests/domain/test_client_lifecycle_lock_order.py::TestLifecycleStepsNeverWaitOnAReader::test_every_step_completes_once_the_reader_lets_go` (identify, register_callback, detach, depart_lapsed) | covered |

## Tests the implementation mission added

Every test the previous revision of this audit named as missing now exists and is
mapped in the tables above (verified by name against `tests/`):

- `tests/domain/test_client_lifecycle_callbacks.py`: C3, C4, C5, C6, C7, C8, C11, C12, A12, S7, DP7 and the withdrawal rule.
- `tests/domain/test_label_revival.py`: B5 to B9, B11 to B15; B10 is `tests/test_ws_listen.py::test_a_read_loop_frame_from_a_lapsed_survivor_marks_its_scenes`.
- `tests/operations/test_callback_operations.py`: C2, C5.
- `tests/domain/test_client_lifecycle_lock_order.py`: K1, K2.
- `tests/domain/test_menu_presence_model.py`: P-2.

No partition is MISSING. The partials that remain are C1 (marks only; its sink
count is not asserted) and L4 (a menu owner, not an agent), both unchanged.

## Definition of done for the implementation mission

1. Every partition above is covered by a test that exists in `tests/` (checked by
   name); the two partials (C1, L4) are the only exceptions. Whether each new
   test failed before the fix was not re-run in this audit.
2. `menu_presence.tex` and the nine state-model controls re-run unchanged: the
   fixed spec reports no P1, P2 or P3 counter-example and no deadlock; each
   control reports its negation found; the lock model reports no deadlock and its
   inverted control a deadlock. (Done by the model mission, round 2.)
3. `PresenceWrites` is taken once by `ClientLifecycle` and called by it alone for
   every presence write; `CallbackOperations` and `ws_listen` hold none.
   (Checked: neither `operations/callbacks.py` nor `ws_listen.py` names
   `PresenceWrites` or `take_writes`; the structural guard
   `tests/domain/test_presence_writes_only_through_lifecycle.py` reads the source.)
4. No lease ADR is amended; DES-101 is amended for the callback route. The DESIGN.md entry for this work cites DES-057, DES-058,
   DES-064, DES-067, DES-094, DES-098, DES-099, DES-100 and DES-101 (the entry is
   the leader's and is not audited here).
