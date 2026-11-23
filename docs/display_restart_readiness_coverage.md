# Display restart readiness: partitions and refinement audit

Companion: [Z model](display_restart_readiness.tex). Reproduce type checks,
exhaustive safety/deadlock checks, and both fidelity witnesses with:

```bash
bash scripts/verify_readiness_model.sh
```

## State and operation mapping

| Model | Implementation |
| --- | --- |
| candidate / stabilizing / ready / failed | `DisplayReadiness.observe`, `DisplayStability.observe`, `DisplayReadinessError` |
| `Spawn`, `NoCandidate`, `Crash` | `_candidate`: new PID required; a later missing/replaced candidate fails |
| `generation`, `Dial`, `Drop` | `DialGeneration.ref`, immutable `GenerationRef` token, `ClientRegistry.asks` reconnect |
| `Begin`, `LocalDone` | `ReadinessProbe.local`: one Unix connection plus kernel peer credentials |
| `Snapshot` | `DisplayQuery.run` attaches the pinned request port's `hub_connection_id`; `HubDisplayProbe` validates PID |
| `Finish` | `DisplayStability.observe` uses the Hub reply timestamp, not the later local-probe completion time |
| `Wait`, `Spend` | `DisplayReadiness.polls`, `_remaining`, and `ReadinessHTTP` per-raw-read deadlines |
| `ProbeError` | local witness loss, unreachable/malformed Hub, and readiness-error logging |
| `Finished` | return or raise; no further readiness probes |

The bounded carrier has two dial names, a three-tick window and six-tick deadline.
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
| One dial, elapsed below / exactly at window | `service/test_display_readiness.py::test_success_requires_three_seconds_of_matching_hub_facts` |
| Same PID, different dial mid-window | `service/test_display_readiness.py::test_same_pid_on_a_replacement_hub_dial_restarts_the_window` |
| Dial names are real, stable and distinct | `hub/test_generation_ref.py`; UUID creation is not stubbed |
| Real names survive query-to-window pipeline | `operations/test_display_query.py::test_real_dial_names_survive_query_resolution_and_reset_stability` |
| Pending probe after a successful observation | `service/test_display_readiness.py::test_a_pending_hub_probe_restarts_stability_without_claiming_a_disconnect` |
| Missing or wrong PID in Hub facts | `service/test_hub_display_probe.py`: mismatched PID, malformed/empty/oversized payload |
| Missing dial metadata | `service/test_hub_display_facts.py`: absent/empty name fails with a Hub-restart instruction |
| HTTP 503/504 / client timeout | `service/test_hub_display_probe.py`: pending status/timeout cases |
| Hub absent, refused, unexpected status | `service/test_hub_display_probe.py`: actionable errors and connection cleanup |
| Every local/Hub probe receives remaining budget; no work after expiry | `service/test_display_readiness.py::test_local_and_hub_probes_share_the_remaining_deadline` |
| Local post-check cannot age a Hub sample | `service/test_display_readiness.py::test_local_probe_time_cannot_age_the_preceding_hub_sample` |
| Response arrives beyond total deadline | `service/test_display_readiness.py::test_probe_cannot_turn_a_deadline_overrun_into_success` |
| Real live owner / wrong owner / absent socket / connect error | `service/test_readiness_probe.py`; live-owner test uses real Unix socket credentials |
| HTTP header/body parser uses budgeted reader | `service/test_readiness_http.py`: real socketpair plus real TCP connection through the response factory |
| Later raw reads shrink budget; exhausted read starts no I/O | `service/test_readiness_http.py::test_a_later_read_gets_only_the_remaining_budget_and_expiry_starts_no_io` |
| Failure diagnostics preserve reason, label and bounded stderr | `service/test_display_readiness.py`, `service/test_restart_readiness.py` |

## Fidelity and remaining limits

Safety is checked as unreachable bad-state goals, following `board_ordering.tex`:
putting safety into the state predicate would disable defective transitions and
make a fidelity check meaningless. The verifier generates variants changing only
the `RESETDIAL` or `BOUNDWORK` axiom. The former must reach ready on a dial younger
than the window; the latter must reach tick seven. The fixed model must exhaust
all states without either defect or a deadlock. Terminal self-loops model a
finished observer, not continued I/O.

Clock-controlled observer tests stub external witnesses deliberately; they do
not by themselves prove the socket or dial-name mechanism. The separate real
credential, real-token pipeline and real-TCP tests cover those boundaries without
stubbed ownership or fabricated identity. A locked-screen macOS crash and native
launchd behavior remain manually unverified. Automatic stderr redirection remains
outside this change; the tail is explicitly best-effort.

## Verification record

```text
PASS: display_restart_readiness fuzz
PASS: no-reset fuzz
PASS: unbounded fuzz
PASS: I1-I4-safety not found (12820 states)
PASS: deadlock not found (12820 states)
PASS: reconnect-fidelity found (1135 states)
PASS: deadline-fidelity found (60 states)
PASS: all readiness model checks
```

The reconnect trace first samples dial 1 at tick 1, then samples replacement dial
2 born at tick 5. With reset disabled, `started=1` survives and `Finish` reaches
ready with age zero. The deadline trace starts probe work at tick 1 and performs
three two-tick spends with bounding disabled, reaching tick 7. These are expected
bad-state witnesses, not failures of the fixed observer.
