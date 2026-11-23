# Display restart readiness: partitions and refinement audit

Companion: [Z model](display_restart_readiness.tex). Reproduce type checks,
exhaustive safety/deadlock checks, and every fidelity witness with:

```bash
make check-models
# Override PROBCLI if it is not installed at ~/Applications/ProB/probcli.
```

## State and operation mapping

| Model | Implementation |
| --- | --- |
| candidate / stabilizing / ready / failed | `DisplayReadiness.poll` / `observe`, `DisplayStability.observe`, `ReadinessError` |
| `Spawn`, `NoCandidate`, `Crash`, `Replace` | `_candidate`: new PID required; a later missing/replaced candidate fails |
| `generation`, `Dial`, `Drop` | `DialGeneration.connection_id`, process/start/serial names pinned by `DisplayRequests`, `ClientRegistry.asks` reconnect |
| `Begin`, `LocalDone` | `ReadinessProbe.local`: one Unix connection plus kernel peer credentials |
| `Snapshot`, `StaleSnapshot`, `Receive` | `DisplayQuery.run` captures the pinned dial; delivery/body parsing can follow that capture |
| `Finish` | `DisplayStability.observe` starts at first receipt, crediting only through each later request's send point |
| `observedSince` | Independent ghost of the first consecutive receipt for the observed dial, even if the implementation timer fails to reset |
| `Wait`, `Spend` | `DisplayReadiness.polls`, `ProbeDeadline.remaining`, and ordinary HTTP socket timeouts and an absolute-deadline shutdown watchdog |
| `ProbeError`, `TransportPending` | verified local witness loss fails; polling PID lookup timeouts (idle work) and Hub transport failures reset stability and remain pending until the deadline |
| `Finished` | return or raise; no further readiness probes |

The bounded carrier has two dial names, an old/new/successor/gone PID carrier,
a three-tick window and six-tick deadline. The chosen candidate is pinned at
`Begin`; `StaleSnapshot` independently samples the old Hub PID, while `Replace`
changes the live local PID only after that choice. Ready requires the sample,
live process and pinned candidate to agree.
Tick seven is representable so deadline safety is tested, not assumed by typing.
This is bounded verification, not a proof of arbitrary clocks or future uptime.
The invariant is about the connection at the accepted Hub sample. Crash/reconnect
after that sample cannot be ruled out by an observer. OS scheduling, local
filesystem latency, and failure-only diagnostic logging are outside the clock
abstraction. Socket operations are assumed to honor the timeout supplied to them.

## Derived partitions

Paths below are relative to `tests/`.

| Operation partition | Test evidence |
| --- | --- |
| No new candidate; old PID persists | `service/test_display_restart.py`: unchanged PID timeout and fresh-install success |
| Candidate exits before first Hub reply | `service/test_display_readiness.py::test_crash_before_hub_connect_fails_without_accepting_respawn` |
| Candidate exits or loses ownership during stability | `service/test_display_readiness.py::test_crash_or_disconnect_during_stability_fails` |
| One dial, elapsed below / exactly at window; an old dial cannot shorten observation | `service/test_display_readiness.py::test_success_requires_three_seconds_of_matching_hub_facts`; `service/test_display_stability.py::test_a_preexisting_dial_still_needs_a_full_observation_window` |
| Same PID, different dial mid-window | `service/test_display_readiness.py::test_same_pid_on_a_replacement_hub_dial_restarts_the_window` |
| Dial names are real, stable and distinct; capabilities carry no token | `hub/test_dial_generation.py`; `hub/test_generation_ref.py` |
| Real names survive query-to-window pipeline | `operations/test_display_query.py::test_real_dial_names_survive_query_resolution_and_reset_stability` |
| Pending probe after a successful observation | `service/test_display_readiness.py::test_a_pending_hub_probe_restarts_stability_without_claiming_a_disconnect` |
| PID lookup times out before or during stability, then recovers; repeated timeouts retain their cause until the deadline | `service/test_display_readiness.py::test_lookup_timeout_is_pending_and_restarts_the_stability_window`; `service/test_display_readiness.py::test_lookup_timeouts_wait_for_the_deadline_and_name_the_last_error` |
| Missing or wrong PID in Hub facts | `service/test_hub_display_probe.py`: mismatched PID, malformed/empty/oversized payload |
| Missing dial metadata | `service/test_hub_display_facts.py`: absent/empty name fails with a Hub-restart instruction |
| HTTP 503/504 / client timeout | `service/test_hub_display_probe.py`: pending status/timeout cases |
| Hub absent, refused, reset, unexpected status | `service/test_hub_display_probe.py`; `service/test_display_readiness.py`: recovery, reset and last-error timeout; real refused-then-live Hub in `service/test_display_restart_end_to_end.py` |
| Every local/Hub probe receives remaining budget; no work after expiry | `service/test_display_readiness.py::test_local_and_hub_probes_share_the_remaining_deadline` |
| Local post-check cannot age a Hub sample | `service/test_display_readiness.py::test_local_probe_time_cannot_age_the_preceding_hub_sample` |
| Delivery after capture cannot finish stability; first connection cannot inherit pre-request time | `service/test_display_readiness.py::test_reply_delivery_time_cannot_finish_the_window`; `service/test_display_stability.py::test_only_time_between_first_receipt_and_latest_send_is_credited` |
| Response arrives beyond total deadline | `service/test_display_readiness.py::test_probe_cannot_turn_a_deadline_overrun_into_success` |
| Real live owner / wrong owner / absent socket / connect error | `service/test_readiness_probe.py`; live-owner test uses real Unix socket credentials |
| Normal HTTP parser retains body bytes | `service/test_readiness_http.py`: real TCP, normal HTTPConnection, persistent and close replies |
| Connection-close body survives HTTPConnection closing its handle | `service/test_readiness_http.py`: both persistent and close replies, with bodies larger than the header buffer |
| Slow body trickles cannot renew the absolute deadline | `service/test_readiness_http.py::test_slow_body_trickle_cannot_extend_the_absolute_deadline`: deterministic expiry interrupts real reads for persistent and close replies |
| Failure diagnostics preserve reason, label and fresh bounded stderr | `service/test_display_readiness.py`: fresh mtime printed, stale file omitted; `service/test_restart_readiness.py` |
| Connection first appears at 28s; polls stop at expiry; pgrep runs only when its fixed 2s timeout fits; a known candidate can finish through local/Hub witnesses in the final 1.5s | `service/test_display_readiness.py`: late-connect, polling, bounded-process-query and last-second stability cases; `service/test_display_restart_scope.py`: cached candidate and expiry cases |
| Live PID with no owned socket | `service/test_display_readiness.py::test_live_pid_without_local_socket_names_the_missing_witness` |
| Real readiness path without witness stubs | `service/test_display_restart_end_to_end.py`: actual pgrep, child PID, Unix peer credentials, local HTTP facts, immediate and refused-then-live Hub |
| GET /display retains the pinned Hub dial name | `rest/test_display_routes.py::test_get_display_info_returns_the_typed_record` |
| Verification gate rejects absent tools, empty/error reports and tolerates output spacing | `service/test_verify_readiness_model.py` |

## Fidelity and remaining limits

Safety is checked as unreachable bad-state goals, following `board_ordering.tex`:
putting safety into the state predicate would disable defective transitions and
make a fidelity check meaningless. The verifier generates variants changing only
one of `RESETDIAL`, `BOUNDWORK`, `SAMPLEBOUND`, `ACCEPTAFTER`, `MATCHHUBPID`,
or `KEEPLOCALPID`. Disabling dial reset or crediting
receipt-time delivery must reach ready on a dial younger than the window;
unbounded work must reach tick seven. A two-tick acceptance threshold must reach
ready with less than three ticks of credited observation despite a dial age of
at least three. The independent observation ghost never affects acceptance;
checking its credit prevents age-only false confidence. The fixed model must exhaust
all states without any bad-state invariant or a deadlock. Stale-PID and
successor-PID mutants must each reach Ready, while the fixed gates reject both. Terminal self-loops model a
finished observer, not continued I/O.

Clock-controlled observer tests stub external witnesses deliberately; they do
not by themselves prove the socket or dial-name mechanism. The separate real
credential, real-name pipeline and real-TCP tests cover those boundaries without
stubbed ownership or fabricated identity. A locked-screen macOS crash and native
launchd behavior remain manually unverified. Generated launchd plists omit
StandardErrorPath; a separately redirected stderr file is included only when its
mtime is at least as new as this restart.

## Verification record

```text
PASS: display_restart_readiness fuzz
PASS: no-reset fuzz
PASS: unbounded fuzz
PASS: receipt-credit fuzz
PASS: short-window fuzz
PASS: stale-pid fuzz
PASS: second-pid fuzz
PASS: I1-I7-safety not found (160126 states)
PASS: deadlock not found (160126 states)
PASS: reconnect-fidelity found (34521 states)
PASS: deadline-fidelity found (297 states)
PASS: delivery-fidelity found (68031 states)
PASS: short-window-fidelity found (30818 states)
PASS: stale-pid-fidelity found (20646 states)
PASS: second-pid-fidelity found (71272 states)
PASS: all readiness model checks
```

The reconnect witness retains the first dial's timer when another dial arrives;
the accepted sample is too young. The deadline witness crosses tick six with
work bounding disabled. The delivery witness credits time after capture, while
the shortened-window witness accepts less than three ticks of actual observation
even though the dial itself is old enough. The stale-PID witness accepts an old
Hub PID despite a live new local PID. The successor-PID witness accepts a
crash-loop replacement after the original candidate has been pinned. These are
expected counterfactual witnesses, not failures of the fixed observer.

The fixed model exhausts the same 160126 states in both safety and deadlock runs.
The parser unit tests independently exercise formatting drift, missing tools and
empty/error output rather than stubbing the model-checking result in the gate.
