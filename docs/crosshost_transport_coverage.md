# Cross-Host Transport: Test Partition Coverage Audit (W12, lux-833p)

This audit maps the test partitions of the two W12 Z specifications to the
tests that cover them, and states plainly which partitions are discharged
by exhaustive model-checking rather than by any finite sample of unit
tests. It is the companion to:

- [`crosshost_connection_lifecycle.tex`](./crosshost_connection_lifecycle.tex)
  — Invariant 1, "no content before verification" (§ R1–R9).
- [`crosshost_hubid_preemption.tex`](./crosshost_hubid_preemption.tex)
  — Invariant 2, "at most one live connection per `HubId`" (§ Q1–Q6).

Re-run `fuzz` and the model-checks (commands in each `.tex`'s Verification
section) whenever the modeled code changes:
`display/cross_host_listener.py`, `display/cross_host_verification.py`,
`display/hub_reconciliation.py`, `display/client_registry.py`,
`display/identity_guard.py`.

## What a model-check discharges that a unit test cannot

Two facets of these invariants are not sampleable:

1. **Exhaustive absence of a bad state.** A unit test shows that _one_
   interleaving is safe. The invariant is that _every_ interleaving is
   safe. `probcli -model_check` visits every reachable state over a
   bounded carrier (setsize 3) and proves the negation of the invariant is
   unreachable — the merge gate for W12. The unit tests below cover the
   individual transitions; the model-check covers their composition.
2. **N-way concurrent reconnect.** Invariant 2 generalizes DES-068's
   single-Hub preemption to N concurrently-reconnecting Hubs. No empirical
   test can enumerate the interleavings of N connect/reconnect/disconnect
   events without becoming a timing-sensitive flake; the model-check does
   it exhaustively (partition Q6). An empirical N-way concurrency test is
   deliberately **not** added — it would sample a space the proof already
   covers in full and reintroduce the load sensitivity the slow-test class
   exists to avoid.

Every fidelity control is model-checked to reproduce its defect and
isolate the other gate — this is what makes the proof trustworthy, per the
WORKFLOW.md fidelity requirement:

| Fidelity control | Reproduces (goal FOUND) | Isolates (goal NOT found) |
|---|---|---|
| `crosshost_connection_lifecycle_no_handshake_gate_buggy.tex` | I1 neg: identified ∧ ¬handshook | I2 (still holds) |
| `crosshost_connection_lifecycle_no_identify_gate_buggy.tex` | I2 neg: served ∧ ¬identified | I1 (still holds) |
| `crosshost_hubid_preemption_name_keyed_buggy.tex` | I1 neg: two live share a HubId (double-owner); and W2 destroyed | — (one key choice breaks both facets) |

## Invariant 1 — connection lifecycle (no content before verification)

| # | Partition | Covered by | Status |
|---|---|---|---|
| R1 | An accepted, un-handshaken connection is not readable (pending set ≠ reader set) | `test_cross_host_listener.py::test_the_pending_set_is_empty_once_no_connection_is_outstanding`; `CrossHostListener` holds pending sockets apart from `_clients`/`_readers` by construction (`test_a_valid_client_certificate_completes_the_handshake` only promotes after `pump_ready`) | Covered (structural + unit) |
| R2 | Gate 1 promotes on handshake success | `test_cross_host_listener.py::test_a_valid_client_certificate_completes_the_handshake`; `test_cross_host_coexistence.py` (`_drive_until_tls_ready` registers only what `pump_ready` returns) | Covered |
| R3 | The between-gates window is real (handshaken, readable, not yet identified, content-refused) | `test_identity_guard.py::test_an_unidentified_fd_is_rejected`, `::test_an_unidentified_fd_is_rejected_and_closed`; model witness W2 (`handshook ∧ ¬identified` reachable) | Covered |
| R4 | Gate 2 identifies on SAN match | `test_hub_reconciliation.py::test_a_matching_hostname_is_identified_normally`; `test_cross_host_verification.py::test_a_matching_hostname_is_not_rejected`, `::test_a_real_peer_naming_its_own_host_is_accepted` | Covered |
| R5 | Gate 2 rejects, fail-closed, on SAN mismatch (and on absent/multi/unusable cert) | `test_hub_reconciliation.py::test_a_mismatched_hostname_is_rejected_closed_and_never_identified`, `::test_a_mismatch_is_never_preempted_as_a_stale_hub`; `test_cross_host_verification.py::test_a_mismatched_hostname_is_rejected`, `::test_no_certificate_is_rejected`, `::test_a_certificate_with_no_san_is_rejected`, `::test_a_certificate_with_two_sans_is_rejected`, `::test_an_unusable_certificate_logs_a_warning`, `::test_a_non_valueerror_parse_failure_is_still_rejected` | Covered (dense) |
| R6 | Content only past both gates (served ⊆ identified ⊆ handshook) | `test_identity_guard.py::test_a_hub_kind_fd_is_not_rejected` (accept path) with R3/R5 (refuse paths); **the composition served ⊆ handshook is the model-checked I1 ∧ I2** | Covered (unit transitions + model-check composition) |
| R7 | An un-handshaken connection never serves content (variant A regression) | Structural: a pending socket is never in the reader set, so `poll_clients` never delivers its frame; **model-check: I1 neg unreachable in the correct spec, FOUND in `..._no_handshake_gate_buggy.tex`** | Covered (structural + fidelity model-check) |
| R8 | An unidentified connection never serves content (variant B / the W1 gap) | `test_identity_guard.py::test_an_unidentified_fd_is_rejected_and_closed`, `::test_a_test_kind_fd_is_rejected_and_closed`; `test_hub_reconciliation.py::test_a_manifest_from_an_unidentified_fd_is_rejected`; **model-check: I2 neg FOUND in `..._no_identify_gate_buggy.tex`** | Covered (unit + fidelity model-check) |
| R9 | A drop at any stage removes the connection cleanly | `test_client_registry.py::test_forget_connection_drops_everything_but_the_hub_id`, `::test_clear_drops_every_connections_state`; `test_cross_host_coexistence.py` (closing the TLS leg leaves AF_UNIX untouched) | Covered |

Witnesses (model-checked, must be FOUND): content actually processed
(`served > 0`) and the between-gates window (`handshook ∧ ¬identified`) —
both reachable, so the invariants do not hold vacuously.

## Invariant 2 — HubId preemption (at most one live connection per HubId)

| # | Partition | Covered by | Status |
|---|---|---|---|
| Q1 | A same-`HubId` reconnect preempts its predecessor | `test_hub_reconciliation.py::test_a_second_hub_identify_forcibly_disconnects_the_first`; `test_client_registry.py::test_hub_fd_for_finds_the_matching_hub_id_connection` | Covered |
| Q2 | A different-`HubId` identify preempts nothing (coexistence, witness W1) | `test_hub_reconciliation.py::test_a_different_hub_id_identify_is_not_preempted`; `test_client_registry.py::test_hub_fd_for_distinguishes_two_hub_ids_sharing_the_same_name`; `test_cross_host_coexistence.py` | Covered |
| Q3 | A same-name, different-`HubId` pair coexists (witness W2 — the regression against name-keying) | `test_hub_reconciliation.py::test_two_hub_ids_sharing_the_same_name_both_stay_connected`; `test_client_registry.py::test_hub_fd_for_distinguishes_two_hub_ids_sharing_the_same_name`; **model-check: W2 FOUND in the correct spec, NOT found in `..._name_keyed_buggy.tex`** | Covered (unit + fidelity model-check) |
| Q4 | A same-`HubId`, different-name reconnect still preempts (name plays no role) | `test_hub_reconciliation.py::test_a_reconnect_under_a_different_name_but_same_hub_id_still_preempts`, `::test_a_reconnect_differing_only_in_declared_hostname_case_preempts` | Covered |
| Q5 | An ordinary disconnect releases the identity (reclaimable, no residual owner) | `test_client_registry.py::test_forget_connection_drops_everything_but_the_hub_id`, `::test_forget_hub_id_drops_the_last_surviving_fact`, `::test_clear_prevents_a_recycled_fd_from_inheriting_a_departed_identity`; composed with `test_hub_reconciliation.py::test_a_hub_identify_with_no_predecessor_preempts_nothing` | Covered (by composition) |
| Q6 | N-way interleaving preserves one-per-`HubId` | **Model-check only** — `hubOf` injective on `live` over all reachable states, setsize 3; no empirical N-way concurrency test (deliberately, see "What a model-check discharges" above) | Covered (model-check; correctly not a unit test) |

Witnesses (model-checked, must be FOUND): two different-`HubId`
connections coexist (W1), and two of them sharing a name coexist (W2) —
both reachable in the correct spec, so at-most-one-per-`HubId` is not
vacuous, and W2's unreachability under name-keying is the wrong-eviction
defect W11 fixes.

## Gaps

None requiring a new test. Every per-transition partition is covered by an
existing unit or integration test; every interleaving/exhaustiveness
partition (R6/R7 composition, Q6) is discharged by an exhaustive
model-check whose fidelity is proven by a buggy control that reproduces the
exact defect. Adding an empirical N-way concurrency test for Q6 is
explicitly declined: it would sample a space the proof already covers in
full and would be a timing-sensitive flake, exactly the class the
slow-test policy (`tests/CLAUDE.md`) keeps out of the serial gate.

## Errata for `hub_display_reconciliation.tex`

That model represents a Hub connection's identity as a bare
`CONNECTION_ID` with no name/`HubId` distinction, and its HI4
("preemption scopes to the shared name") states the pre-W11 rule. Its own
SUPERSEDED banner points here. `crosshost_hubid_preemption.tex` is
authoritative for Invariant 2: preemption scopes to the shared `HubId`;
two connections sharing a name but declaring distinct `HubId`s coexist,
and only a same-`HubId` arrival preempts.
