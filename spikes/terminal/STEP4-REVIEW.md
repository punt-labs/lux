# Step 4 review and acceptance ledger

This is a spike handoff, not merge authorization. The independent-owner
implementation is present; do not silently turn partial acceptance evidence
into “production ready.” The original plan and historical performance claims
are qualified below. Canonical architecture remains Lux's DESIGN/target docs.

## Implemented and demonstrated

- [x] Native binary snapshot, history and bounded continuation round trips;
  visible-state VT utility is not presented as lossless persistence.
- [x] Authenticated private Unix service parses without viewers, answers program
  queries once, retains processes/screens and does not respawn exited programs.
- [x] Actual-window Display close/restart and SIGKILL/restart preserve program
  lifetime. Newer screenshots/OCR also establish visible marker restoration
  after Hub scene replay, not just an unchanged PID.
- [x] Credit including snapshot fragments, bounded lag repaint and preserved old
  debt; fast/slow-viewer finite-burst integration.
- [x] Several production replica pools share one process, synchronize resize and
  survive another viewer closing; passive geometry avoids resize ping-pong.
- [x] Machine-enabled launcher (subsequent operator requirement, ADR-0008): local
  supervisor commands, daemon-owned persistent Terminal menu, registration without
  starting a shell, routed launch/reopen and Hub-restart recovery. Display does not
  enable/start a missing owner. `--no-menu` retains headless idle semantics.
- [x] Bounded partial-send/coalesced socket output and measured ACK-backlog fix.
- [x] Finite local reconnect/flood measurements, actual Hub/Display control-path
  ping during a GUI burst, raw reports and reproducible manual helpers.
- [x] Formal attach, child, peer, credit and daemon models with fidelity mutations,
  PDFs and coverage-gap reports.
- [x] ADR-0007 supersedes the Display lifetime/pump part of ADR-0006. README,
  changelog and known limitations describe the current implementation.
- [x] Strict whole-repository typing/lint and all quality ratchets; no relaxed
  thresholds, no added source suppressions. Scoped tests and integrations only.

## Original acceptance experiments: current evidence and gaps

- [x] Two **actual GUI windows** attached simultaneously to one session. The
  PID-selected/OCR-checked two-window run also kills one Display, sends a new
  update visible in the survivor, and rejoins the crashed window without
  changing the program or daemon PID. See STEP4-LIVE.md and results/two-windows.json.
- [ ] End-to-end real keyboard-to-pixel latency under flood and a heavy
  neighboring 1,000-row table. Hub/Display ping and replica response timing do
  not substitute for these measurements. The OS-input diagnostic renders the
  table but fails to establish warm key delivery; it is not promoted to a passing
  test (STEP4-KEYBOARD-PROBE.md). STEP3's older FPS numbers are historical.
- [ ] Exhaustive pixel/native-state fidelity across interactive applications,
  many terminals, docking and high-DPI/font variations after this lifetime move.
- [ ] Long-duration memory/FD/process soak and maximum-throughput characterization.
  Twenty bounded lifecycle cycles are now recorded (STEP4-LIFECYCLE-CYCLES.md):
  FD counts stable and sampled direct-child lists empty. They do not close the
  long-duration/descendant/memory/resource-policy gap.

These are explicit acceptance gaps, not thresholds that were relaxed.

## Lifecycle policy clarification

The early plan said a cycle leaves “no process and no file.” Runtime lock/log
files intentionally persist privately. Deleting an open flock inode permits
old/new-inode ownership races; the safe policy is a stable reusable inode.
A clean cycle leaves no owned program/daemon or socket, and an isolated test
removes its instance directory after all processes stop. It does not delete
normal per-user runtime state after every idle exit. ADR-0007 records this
change rather than claiming zero-file cleanup was demonstrated.

## Targeted review findings

### Fixed: initial snapshot failure became a permanent Display failure

A program emits a 70,000-byte unfinished OSC sequence, exceeding the tracked
continuation bound. The original reconnect received a failure envelope and
remained FAILED even after native parser ground. The failing real-daemon test
reproduced this. Initial snapshot unavailability now closes only that viewer
connection; the normal bounded reconnect path retries, restoring GROUND_READY
with the **same PID**. No program or other peer is killed. Lag repaint's existing
retry path remains independent. Persistent snapshot resource/size failures
still need better product diagnostics.

### Fixed: unsupported daemon stream directions were silently ignored

Replica receive now rejects CREDIT/RESIZE in the daemon-to-viewer direction.
They are client-to-daemon operations in wire-v2. Unit tests prevent silent
acceptance of malformed direction; the connection owner handles protocol failure.

### Previously fixed: tiny ACK queue ahead of input

One frame per flush serialized hundreds of small ACKs ahead of keyboard data.
Bounded batching retains exact FIFO/partial-send semantics and improves the
recorded finite-burst result. See STEP4-PERFORMANCE.md. A smaller PTY parse/read
slice did not help and was reverted, not retained as speculative optimization.

### Explicit remaining concerns

- Fixed transport-level allocation/grouped construction-cleanup failure escape:
  ControlFailures returns a bounded failure reply while retaining failed-cleanup
  ownership and leaving other sessions alive. Twelve socket/core fault cases
  cover successful/refused cleanup, nonempty/empty errors and operator signals.
  SystemExit/KeyboardInterrupt and their BaseExceptionGroup forms propagate.
  This is injected operation-fault coverage, not a claim that true process-wide
  memory exhaustion can always be recovered.
- Same-UID shell authority is not agent consent or a render-command capability.
  Hub/renderer authorization and session namespace/cleanup policy need adoption
  review; hiding behind socket UID validation would be incorrect.
- Snapshot/history/grid bounds are not a complete memory budget. Persistent
  unencodable/oversize state needs actionable diagnostics and bounded retry policy.
- Private append-only daemon log needs an operational retention/rotation policy.
- Cold first-use includes a one-second connection retry. Flooded terminal input
  remains slower than quiet input. Reported timing is local, finite and small-N.
- Global RemoteSessions facade is known dependency-injection debt.
- Daemon upgrades/crashes do not preserve programs; no remote transport, replay,
  blackboard/mesh merger, voice routing or public agent terminal API is implemented.

This review is a local source/test audit, not an independent external review.

## Merge prerequisites (operator decision required)

- [ ] Authorize a PR/merge; none has been opened or performed for this spike.
- [ ] Reconcile with current main in the isolated clone and resolve conflicts
  without disturbing normal Lux services. Gate thresholds must not be weakened.
- [ ] Run the broader macOS suite when authorized; it has intentionally not run
  under the current operator constraint.
- [ ] Verify Linux PTY, credentials, detached spawn, packaging and fonts. Windows
  is not supported by this spike's current native wheel/PTY implementation.
- [ ] Complete the outstanding keyboard/render checks; the actual simultaneous
  multi-window acceptance case is now demonstrated.
- [ ] Independent review of protocol, FD/PID ownership, native ABI/resource bounds
  and the shell-authority/consent implications of terminal rendering.
- [ ] Decide shipping/default-enable policy, dependency packaging and native API
  maintenance. pyghostty 0.1.4 is exactly pinned and uses private API.
- [ ] Convert adopted spike ADRs into canonical DES entries if approved.

## Latest verification

- Scoped `make check BASE_REF=3712972`: **850 passed, 22 integration deselected**.
- Separately all **22 integration tests passed** in sequential isolated sets under timeout.
- Whole-repository typing: zero errors, seven existing native ImGui source warnings.
- OO/coupling/suppression gates pass; source suppression count remains **123**.
- No test daemon remains; isolated children/sockets/instance cleanup completed.

## Verification commands

```sh
PYTEST_ADDOPTS='tests/ptyd tests/protocol tests/render tests/display/test_display_setup.py tests/test_protocol.py tests/test_frame_geometry_timing.py tests/test_frame_placement.py tests/test_frame_tiling.py tests/test_frame_entry_order_agreement.py tests/test_markdown_font.py tests/test_per_frame_tracing.py tests/test_renderers_import_fallback.py' \
  timeout 420 make check BASE_REF=3712972
timeout 120 .venv/bin/python -m pytest tests/ptyd/test_core_live.py tests/ptyd/test_holder_live.py -o addopts='' -q
timeout 120 .venv/bin/python -m pytest tests/ptyd -m integration --ignore=tests/ptyd/test_core_live.py --ignore=tests/ptyd/test_holder_live.py -o addopts='' -q
```

Cold demand-start timing is historical after machine opt-in superseded it;
current launcher evidence is TERMINAL-LAUNCHER-RESULTS.md. Native in-process
fork tests run separately from Hub/CLI thread fixtures, without warning suppression.

Run benchmarks/manual GUI checks separately and sequentially with the documented
hard limits. Stop owned children/sockets/instances. Never touch normal Lux,
gpg-agent, password stores or signing material during verification.
